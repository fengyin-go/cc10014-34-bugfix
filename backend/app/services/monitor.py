"""服务监控业务规则：状态流转、字段校验与筛选口径都收在这里。

重点约束：
- 登记时八个业务字段都要落库，缺任何一个都返回缺失字段，不允许静默丢弃；
- 状态只能按 草稿 → 待校验 → 已启用 → 已停用 顺序推进，草稿不能直接启用；
- 启用时固化「时间窗 / 日志来源 / 阈值版本」，停用时同步写入同一个截止边界，
  让后续聚合与日志范围立即失配。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.timeutil import format_time, parse_minutes, parse_number, utc_now
from app.store import store

MODULE = "monitor"
REQUIRED_FIELDS = [
    "指标编号",
    "关联服务",
    "QPS阈值",
    "延迟阈值",
    "错误率阈值",
    "告警级别",
    "通知渠道",
    "静默分钟",
]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用监控": "已启用", "停用监控": "已停用"}
NEGATIVE_ACTIONS = ["停用监控"]
ALLOWED_TRANSITIONS = {
    "提交校验": {"草稿", "已停用"},
    "启用监控": {"待校验"},
    "停用监控": {"已启用"},
}
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_PRIORITY = 0


class MonitorService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("指标编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 指标列表固定按「优先级高、版本新、编号小」展示，避免同一窗口两个版本时旧阈值排在前面。
        rows = sorted(rows, key=_display_order)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_with_effective(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _with_effective(entry) if entry is not None else None

    def find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("指标编号", "")) == code:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        code = str(values.get("指标编号") or "").strip()
        if self.find_by_code(code) is not None:
            return None, [f"指标编号 {code} 已存在"]
        if parse_number(values.get("QPS阈值")) is None:
            return None, ["QPS阈值必须是数字"]
        if parse_number(values.get("延迟阈值")) is None:
            return None, ["延迟阈值必须是数字"]
        if parse_number(values.get("错误率阈值")) is None:
            return None, ["错误率阈值必须是数字"]
        if parse_number(values.get("静默分钟")) is None:
            return None, ["静默分钟必须是数字"]
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["时间窗分钟"] = parse_minutes(values.get("时间窗分钟"), DEFAULT_WINDOW_MINUTES)
        entry["日志来源"] = _split_sources(values.get("日志来源"))
        entry["优先级"] = _parse_priority(values.get("优先级"))
        entry["阈值版本"] = int(parse_number(values.get("阈值版本")) or 0)
        entry["生效开始"] = None
        entry["截止边界"] = None
        entry["日志范围起"] = None
        entry["日志范围止"] = None
        entry["最近聚合时间"] = None
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        _propagate(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """修改阈值类字段：版本号必须递增，旧版本要留档，避免列表页残留旧阈值。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"监控指标 {entry_id} 不存在或已归档"
        editable = [
            "关联服务",
            "QPS阈值",
            "延迟阈值",
            "错误率阈值",
            "告警级别",
            "通知渠道",
            "静默分钟",
            "时间窗分钟",
            "日志来源",
            "优先级",
        ]
        # 列表页与告警详情都读契约里的生效阈值，修改后立刻同步，避免残留旧阈值。
        changed = {field: values[field] for field in editable if field in values}
        if not changed:
            return None, "没有可修改的字段"
        for field in ("QPS阈值", "延迟阈值", "错误率阈值", "静默分钟"):
            if field in changed and parse_number(changed[field]) is None:
                return None, f"{field}必须是数字"
        history = entry.setdefault("阈值历史", [])
        history.append({field: entry.get(field) for field in editable} | {"阈值版本": entry.get("阈值版本", 0)})
        entry.update(changed)
        if "时间窗分钟" in changed:
            entry["时间窗分钟"] = parse_minutes(changed["时间窗分钟"], entry.get("时间窗分钟") or DEFAULT_WINDOW_MINUTES)
        if "日志来源" in changed:
            entry["日志来源"] = _split_sources(changed["日志来源"])
        if "优先级" in changed:
            entry["优先级"] = _parse_priority(changed["优先级"])
        entry["阈值版本"] = int(entry.get("阈值版本") or 0) + 1
        entry["阈值变更时间"] = format_time(utc_now())
        entry["pending"] = entry.get("status") != "已启用"
        _propagate(entry)
        return entry, f"监控指标阈值已更新到版本 {entry['阈值版本']}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"监控指标 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于服务监控可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        current = str(entry.get("status") or "")
        allowed = ALLOWED_TRANSITIONS.get(action, set())
        if current not in allowed:
            return None, f"当前状态「{current}」不能执行「{action}」"
        now = utc_now()
        if action == "启用监控":
            self._activate(entry, now)
        elif action == "停用监控":
            self._deactivate(entry, now)
        else:
            entry["status"] = target
            entry["pending"] = True
            entry["abnormal"] = False
        _propagate(entry)
        return entry, f"监控指标已{action}"

    def _activate(self, entry: dict[str, Any], now: datetime) -> None:
        window = parse_minutes(entry.get("时间窗分钟"), DEFAULT_WINDOW_MINUTES)
        sources = _split_sources(entry.get("日志来源"))
        if not sources:
            sources = _split_sources(entry.get("关联服务"))
            entry["日志来源"] = sources
        entry["时间窗分钟"] = window
        entry["status"] = "已启用"
        entry["pending"] = False
        entry["abnormal"] = False
        entry["阈值版本"] = int(entry.get("阈值版本") or 0) + 1
        entry["生效开始"] = format_time(now)
        entry["截止边界"] = None
        # 时间窗和日志范围同步重置：停用后再启用时不会把上一次的截止边界带回来。
        backfill = timedelta(minutes=window)
        entry["日志范围起"] = format_time(now - backfill)
        entry["日志范围止"] = None
        entry["最近聚合时间"] = None

    def _deactivate(self, entry: dict[str, Any], now: datetime) -> None:
        boundary = format_time(now)
        entry["status"] = "已停用"
        entry["pending"] = False
        entry["abnormal"] = False
        entry["截止边界"] = boundary
        entry["日志范围止"] = boundary


def _propagate(entry: dict[str, Any]) -> None:
    """状态/阈值变化后同步契约、批次范围和告警视图。"""
    from app.services import monitor_batch, monitor_contract

    contract = monitor_contract.sync_from_metric(entry)
    monitor_batch.on_metric_change(entry, contract)


def _split_sources(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    for separator in ("，", ";", "；", "|"):
        text = text.replace(separator, ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def _parse_priority(value: object) -> int:
    number = parse_number(value)
    return int(number) if number is not None else DEFAULT_PRIORITY


def _with_effective(row: dict[str, Any]) -> dict[str, Any]:
    """列表/详情附带契约里的生效阈值版本，页面不再单看登记版本。"""
    from app.services import monitor_contract

    monitor_contract.ensure_contracts()
    contract = monitor_contract.find_by_metric(str(row.get("指标编号") or ""))
    view = dict(row)
    if contract is not None:
        view["生效阈值版本"] = contract.get("生效阈值版本") or contract.get("阈值版本")
        view["契约启用状态"] = contract.get("启用状态")
        view["当前范围批次数"] = contract.get("当前范围批次数", 0)
        view["历史范围批次数"] = contract.get("历史范围批次数", 0)
    else:
        view.setdefault("生效阈值版本", row.get("阈值版本"))
    return view


def _display_order(row: dict[str, Any]) -> tuple[int, int, int]:
    return (
        -_parse_priority(row.get("优先级")),
        -int(parse_number(row.get("阈值版本")) or 0),
        int(row.get("id", 0)),
    )

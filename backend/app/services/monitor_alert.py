"""异常告警业务规则：告警只读取监控指标契约里的启用口径。

- 告警详情里的「当前阈值」永远来自契约快照，指标改阈值后由契约同步刷新；
- 指标停用后契约标记停用，告警转历史，截止边界固定下来，不再被迟到日志改写；
- 静默分钟按「同指标 + 同批次」抑制重复通知，但告警证据仍然保留。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.timeutil import format_time, parse_minutes, parse_time
from app.store import store

MODULE = "monitor_alert"
SCOPE_CURRENT = "当前"
SCOPE_HISTORY = "历史"


def list_entries(
    *,
    scope: str | None = SCOPE_CURRENT,
    metric_code: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    rows = store.rows(MODULE)
    if scope in (SCOPE_CURRENT, "当前范围", "current", "活跃"):
        rows = [row for row in rows if row.get("范围类型") == SCOPE_CURRENT]
    elif scope in (SCOPE_HISTORY, "历史范围", "history"):
        rows = [row for row in rows if row.get("范围类型") == SCOPE_HISTORY]
    elif scope in (None, "", "all", "全部"):
        pass
    else:
        rows = [row for row in rows if row.get("范围类型") == scope]
    if metric_code:
        rows = [row for row in rows if str(row.get("指标编号")) == metric_code]
    if status:
        rows = [row for row in rows if row.get("状态") == status]
    rows = sorted(rows, key=lambda row: (-_number(row.get("触发时间")), -int(row.get("id", 0))))
    total = len(rows)
    start = max(page - 1, 0) * size
    return [enrich(row) for row in rows[start:start + size]], total


def get_entry(entry_id: int) -> dict[str, Any] | None:
    row = store.find(MODULE, entry_id)
    return enrich(row) if row else None


def find_by_batch(batch_code: str) -> dict[str, Any] | None:
    for row in store.rows(MODULE):
        if str(row.get("批次编号")) == batch_code:
            return row
    return None


def upsert_for_batch(batch: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    """按批次写入或刷新一条异常告警；只有异常批次才产生告警。"""
    code = str(batch.get("批次编号") or "")
    existing = find_by_batch(code)
    if not batch.get("异常"):
        if existing is not None and existing.get("范围类型") == SCOPE_CURRENT:
            existing["状态"] = "已恢复"
            existing["范围类型"] = SCOPE_HISTORY
            existing["更新时间"] = format_time(datetime.now())
        return existing or {}
    now = format_time(datetime.now())
    snapshot = dict(batch.get("阈值快照") or {})
    if existing is None:
        rows = store.rows(MODULE)
        alert_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        sequence = store.next_sequence("monitor_alert", minimum=_next_code_number(rows, "告警编号", "ALER-"))
        existing = {
            "id": alert_id,
            "告警编号": f"ALER-{sequence:04d}",
            "指标编号": batch.get("指标编号"),
            "契约编号": contract.get("契约编号") if contract else None,
            "批次编号": batch.get("批次编号"),
            "阈值版本": batch.get("阈值版本"),
            "告警级别": snapshot.get("告警级别"),
            "通知渠道": snapshot.get("通知渠道"),
            "静默分钟": snapshot.get("静默分钟"),
            "异常原因": batch.get("异常原因"),
            "触发时间": batch.get("更新时间") or now,
            "首次触发时间": batch.get("创建时间") or now,
            "范围类型": batch.get("范围类型") or SCOPE_CURRENT,
            "状态": "活跃" if batch.get("范围类型") == SCOPE_CURRENT else SCOPE_HISTORY,
            "阈值快照": snapshot,
            "截止边界": batch.get("截止边界"),
            "通知状态": "已通知",
            "更新时间": now,
        }
        rows.append(existing)
    else:
        existing.update({
            "指标编号": batch.get("指标编号"),
            "契约编号": contract.get("契约编号") if contract else existing.get("契约编号"),
            "阈值版本": batch.get("阈值版本"),
            "告警级别": snapshot.get("告警级别", existing.get("告警级别")),
            "通知渠道": snapshot.get("通知渠道", existing.get("通知渠道")),
            "静默分钟": snapshot.get("静默分钟", existing.get("静默分钟")),
            "异常原因": batch.get("异常原因"),
            "触发时间": batch.get("更新时间") or existing.get("触发时间"),
            "范围类型": batch.get("范围类型") or existing.get("范围类型"),
            "状态": "活跃" if batch.get("范围类型") == SCOPE_CURRENT else SCOPE_HISTORY,
            "阈值快照": snapshot or existing.get("阈值快照"),
            "截止边界": batch.get("截止边界"),
            "更新时间": now,
        })
    existing["当前阈值"] = _current_threshold(contract, batch)
    existing["通知状态"] = _notification_state(existing, batch)
    return existing


def refresh_for_metric(metric_code: str, contract: dict[str, Any] | None, cutoff: str | None) -> None:
    """指标改阈值/停用后刷新告警范围与当前阈值，避免详情页继续显示旧阈值。"""
    for row in store.rows(MODULE):
        if str(row.get("指标编号")) != metric_code:
            continue
        if contract is not None:
            row["契约编号"] = contract.get("契约编号", row.get("契约编号"))
            row["当前阈值"] = _current_threshold(contract, None)
        enabled = bool(contract and contract.get("启用状态") == "启用")
        if not enabled:
            row["范围类型"] = SCOPE_HISTORY
            row["状态"] = SCOPE_HISTORY
            row["截止边界"] = cutoff or row.get("截止边界")
        row["更新时间"] = format_time(datetime.now())


def enrich(row: dict[str, Any]) -> dict[str, Any]:
    from app.services.monitor_contract import find_by_metric

    contract = find_by_metric(str(row.get("指标编号")))
    result = dict(row)
    result["当前阈值"] = _current_threshold(contract, None)
    result["指标状态"] = contract.get("指标状态") if contract else None
    if contract and contract.get("启用状态") != "启用":
        result["范围类型"] = SCOPE_HISTORY
    return result


def _current_threshold(contract: dict[str, Any] | None, batch: dict[str, Any] | None) -> dict[str, Any]:
    if contract is not None:
        version = contract.get("阈值版本")
        effective = contract.get("生效阈值快照")
        result = {
            "QPS阈值": contract.get("QPS阈值"),
            "延迟阈值": contract.get("延迟阈值"),
            "错误率阈值": contract.get("错误率阈值"),
            "告警级别": contract.get("告警级别"),
            "通知渠道": contract.get("通知渠道"),
            "静默分钟": contract.get("静默分钟"),
            "阈值版本": version,
            "生效阈值版本": contract.get("生效阈值版本") or version,
        }
        if isinstance(effective, dict) and effective:
            # 同一窗口出现两个阈值版本且旧版本优先级更高时，实际判定依据是旧版本；
            # 这里把生效值一并返回，页面就不会拿新阈值去对照旧批次的告警。
            result["生效阈值"] = effective
        return result
    return dict((batch or {}).get("阈值快照") or {})


def _notification_state(alert: dict[str, Any], batch: dict[str, Any]) -> str:
    if batch.get("范围类型") != SCOPE_CURRENT:
        return "已静默"
    silence = parse_minutes(alert.get("静默分钟"), 5)
    first = parse_time(alert.get("首次触发时间")) or parse_time(alert.get("触发时间"))
    now = parse_time(batch.get("更新时间")) or datetime.now()
    if first and now < first + timedelta(minutes=silence):
        return "静默中"
    return "已通知"


def _next_code_number(rows: list[dict[str, Any]], field: str, prefix: str) -> int:
    numbers = []
    for row in rows:
        text = str(row.get(field) or "")
        if text.startswith(prefix):
            try:
                numbers.append(int(text[len(prefix):]))
            except ValueError:
                continue
    return max(numbers, default=0) + 1


def _number(value: object) -> float:
    parsed = parse_time(value)
    return parsed.timestamp() if parsed else 0.0

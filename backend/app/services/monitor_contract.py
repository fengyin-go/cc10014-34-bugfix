"""监控指标契约：跨模块读取的启用口径快照。

主流程（服务监控）每次改状态或阈值都会同步到这里，指标批次聚合完成后再把批次统计
回写到契约。异常告警只读取这里「启用状态 = 启用」的指标，避免停用后继续按旧阈值告警。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.timeutil import format_time, parse_minutes, parse_number
from app.store import store

MODULE = "monitor_contract"
CONTRACT_ENABLED = "启用"
CONTRACT_DISABLED = "停用"
SNAPSHOT_FIELDS = [
    "QPS阈值",
    "延迟阈值",
    "错误率阈值",
    "告警级别",
    "通知渠道",
    "静默分钟",
]
DEFAULT_WINDOW_MINUTES = 60


def ensure_contracts() -> list[dict[str, Any]]:
    """补齐缺失的契约，并从指标批次回填统计；示例数据首次查询时也能直接读到。"""
    rows = store.rows(MODULE)
    known = {str(row.get("指标编号")) for row in rows}
    for metric in store.rows("monitor"):
        code = str(metric.get("指标编号") or "")
        if code and code not in known:
            sync_from_metric(metric)
    for contract in rows:
        sync_batch_stats(str(contract.get("指标编号") or ""))
    return rows


def sync_from_metric(metric: dict[str, Any]) -> dict[str, Any]:
    """把指标的当前状态/阈值/时间窗/日志范围同步进契约，返回契约行。"""
    code = str(metric.get("指标编号") or "")
    contract = find_by_metric(code)
    if contract is None:
        rows = store.rows(MODULE)
        contract_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        sequence = store.next_sequence("monitor_contract", minimum=_next_code_number(rows, "契约编号", "CONT-"))
        contract = {
            "id": contract_id,
            "契约编号": f"CONT-{sequence:04d}",
            "指标编号": code,
            "创建时间": format_time(datetime.now()),
        }
        rows.append(contract)
    status = str(metric.get("status") or "")
    contract.update({
        "指标状态": status,
        "启用状态": CONTRACT_ENABLED if status == "已启用" else CONTRACT_DISABLED,
        "QPS阈值": metric.get("QPS阈值"),
        "延迟阈值": metric.get("延迟阈值"),
        "错误率阈值": metric.get("错误率阈值"),
        "告警级别": metric.get("告警级别"),
        "通知渠道": metric.get("通知渠道"),
        "静默分钟": metric.get("静默分钟"),
        "时间窗分钟": parse_minutes(metric.get("时间窗分钟"), DEFAULT_WINDOW_MINUTES),
        "日志来源": _sources(metric.get("日志来源") or metric.get("关联服务")),
        "阈值版本": int(parse_number(metric.get("阈值版本")) or 0),
        "优先级": int(parse_number(metric.get("优先级")) or 0),
        "生效开始": metric.get("生效开始"),
        "截止边界": metric.get("截止边界"),
        "日志范围起": metric.get("日志范围起") or metric.get("生效开始"),
        "日志范围止": metric.get("日志范围止") or metric.get("截止边界"),
        "同步时间": format_time(datetime.now()),
    })
    contract.setdefault("最新批次编号", None)
    contract.setdefault("当前批次异常", False)
    contract.setdefault("当前范围批次数", 0)
    contract.setdefault("历史范围批次数", 0)
    contract.setdefault("最近聚合时间", None)
    contract.setdefault("生效阈值版本", contract.get("阈值版本"))
    contract.setdefault("生效阈值快照", contract_snapshot(contract))
    return contract


def sync_batch_stats(metric_code: str) -> dict[str, Any] | None:
    """把指标批次的统计回写给契约：当前/历史范围各有几批、最新批次是否异常。"""
    contract = find_by_metric(metric_code)
    if contract is None:
        return None
    batches = [
        row for row in store.rows("monitor_batch")
        if str(row.get("指标编号")) == metric_code and not row.get("导入标记")
    ]
    current = [row for row in batches if row.get("范围类型") == "当前"]
    history = [row for row in batches if row.get("范围类型") == "历史"]
    latest = None
    if batches:
        latest = sorted(batches, key=lambda row: (str(row.get("更新时间") or ""), int(row.get("id", 0))))[-1]
    contract["当前范围批次数"] = len(current)
    contract["历史范围批次数"] = len(history)
    contract["最新批次编号"] = latest.get("批次编号") if latest else None
    contract["当前批次异常"] = any(bool(row.get("异常")) for row in current)
    contract["最近聚合时间"] = latest.get("更新时间") if latest else None
    # 当前窗口可能因为优先级仲裁仍按旧版本判定；把实际生效版本同步给契约，
    # 列表页与告警详情都读这一份，避免出现「页面显示新阈值、告警按旧阈值」。
    effective = None
    if current:
        effective = sorted(current, key=lambda row: (str(row.get("更新时间") or ""), int(row.get("id", 0))))[-1]
    contract["生效阈值版本"] = (effective or {}).get("阈值版本", contract.get("阈值版本"))
    contract["生效阈值快照"] = (effective or {}).get("阈值快照") or contract_snapshot(contract)
    contract["同步时间"] = format_time(datetime.now())
    return contract


def find_by_metric(metric_code: str) -> dict[str, Any] | None:
    for row in store.rows(MODULE):
        if str(row.get("指标编号")) == metric_code:
            return row
    return None


def list_entries(
    *,
    enabled: str | None = None,
    metric_code: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    ensure_contracts()
    rows = store.rows(MODULE)
    if enabled:
        rows = [row for row in rows if row.get("启用状态") == enabled]
    if metric_code:
        rows = [row for row in rows if str(row.get("指标编号")) == metric_code]
    rows = sorted(rows, key=lambda row: (str(row.get("指标编号") or ""), int(row.get("id", 0))))
    total = len(rows)
    start = max(page - 1, 0) * size
    return rows[start:start + size], total


def get_entry(entry_id: int) -> dict[str, Any] | None:
    ensure_contracts()
    return store.find(MODULE, entry_id)


def contract_snapshot(contract: dict[str, Any] | None) -> dict[str, Any]:
    if not contract:
        return {}
    return {field: contract.get(field) for field in SNAPSHOT_FIELDS} | {
        "阈值版本": contract.get("阈值版本"),
    }


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


def _sources(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    for separator in ("，", ";", "；", "|"):
        text = text.replace(separator, ",")
    return [item.strip() for item in text.split(",") if item.strip()]

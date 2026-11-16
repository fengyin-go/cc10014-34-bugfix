"""监控指标批次：按指标状态与时间窗把调用日志聚合成可复核的批次。

聚合口径（与监控指标契约保持一致）：
1. 只有契约里「启用状态 = 启用」的指标参与聚合，停用指标不再新增或更新任何批次；
2. 日志时间必须落在契约的日志范围内：``日志范围起 <= 请求时间 < 截止边界``；
3. 指标停用时把同一个截止边界写进指标、契约、日志范围与已有批次，批次转「历史」范围；
4. 同一指标同一窗口出现两个阈值版本时，按「优先级高 → 阈值版本新 → 记录 id 小」仲裁，
   仲裁结果和依据都写进批次，便于后续复核；
5. 聚合失败的日志保留失败原因，重试时只从这些失败记录继续。

批次以「指标编号 + 窗口起点」唯一，重复聚合是幂等的：同一批日志不会重复计数。
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.services.timeutil import (
    floor_window,
    format_time,
    parse_minutes,
    parse_number,
    parse_time,
    utc_now,
)
from app.services import monitor_alert, monitor_contract
from app.store import store

MODULE = "monitor_batch"
SCOPE_CURRENT = "当前"
SCOPE_HISTORY = "历史"
LOG_PENDING = "待聚合"
LOG_DONE = "已聚合"
LOG_FAILED = "失败"
LOG_OUT_OF_RANGE = "超范围"
IMPORT_SOURCE = "导入包"
ARBITRATION_ORDER = "优先级高 → 阈值版本新 → 记录 id 小"


def aggregate(*, metric_code: str | None = None, operator: str = "系统") -> dict[str, Any]:
    """按指标状态与时间窗聚合待处理日志，返回本次处理摘要。"""
    _ensure_contracts()
    now = utc_now()
    contracts = _candidate_contracts(metric_code)
    logs = [row for row in store.rows("log") if row.get("聚合状态") in (None, LOG_PENDING)]
    summary = {
        "处理日志": len(logs),
        "已聚合日志": 0,
        "超范围日志": 0,
        "未匹配日志": 0,
        "失败日志": 0,
        "新建批次": 0,
        "更新批次": 0,
        "仲裁": [],
        "批次": [],
        "更新时间": format_time(now),
        "操作人": operator,
    }
    touched: dict[str, bool] = {}
    for log in logs:
        outcome, batch_code, created = _consume_log(log, contracts, now)
        if outcome == LOG_DONE:
            summary["已聚合日志"] += 1
        elif outcome == LOG_OUT_OF_RANGE:
            summary["超范围日志"] += 1
        elif outcome == LOG_FAILED:
            summary["失败日志"] += 1
        else:
            summary["未匹配日志"] += 1
        if batch_code:
            touched.setdefault(batch_code, False)
        if created:
            summary["新建批次"] += 1
        for note in log.get("仲裁记录") or []:
            if note not in summary["仲裁"]:
                summary["仲裁"].append(note)
    # 新建/更新的批次统一重算统计，保证阈值判断与证据一致。
    for code in sorted(touched):
        batch = _find_batch(code)
        if batch is None:
            continue
        _recompute(batch, now)
        summary["更新批次"] += 1
        summary["批次"].append(_batch_brief(batch))
    for contract in contracts:
        monitor_contract.sync_batch_stats(str(contract.get("指标编号") or ""))
    summary["阈值仲裁口径"] = ARBITRATION_ORDER
    return summary


def retry_failed(*, metric_code: str | None = None, operator: str = "系统") -> dict[str, Any]:
    """中断后从失败记录接着重试：只把失败日志放回待聚合，再跑一次聚合。"""
    rows = store.rows("log")
    retried: list[str] = []
    for row in rows:
        if row.get("聚合状态") != LOG_FAILED:
            continue
        if metric_code:
            batch = _find_batch(str(row.get("指标批次") or ""))
            if batch is None or str(batch.get("指标编号")) != metric_code:
                continue
        row["聚合状态"] = LOG_PENDING
        row["重试次数"] = int(row.get("重试次数") or 0) + 1
        row["上次失败原因"] = row.get("失败原因")
        row["失败原因"] = None
        retried.append(str(row.get("记录编号") or row.get("id")))
    result = aggregate(metric_code=metric_code, operator=operator)
    result["重试记录"] = retried
    return result


def list_entries(
    *,
    metric_code: str | None = None,
    scope: str | None = None,
    abnormal: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    rows = store.rows(MODULE)
    if metric_code:
        rows = [row for row in rows if str(row.get("指标编号")) == metric_code]
    if scope:
        rows = [row for row in rows if row.get("范围类型") == scope]
    if abnormal not in (None, ""):
        expected = abnormal in ("1", "true", "True", "异常", "yes")
        rows = [row for row in rows if bool(row.get("异常")) is expected]
    rows = sorted(rows, key=lambda row: (str(row.get("窗口起") or ""), int(row.get("id", 0))), reverse=True)
    total = len(rows)
    start = max(page - 1, 0) * size
    return rows[start:start + size], total


def get_entry(entry_id: int) -> dict[str, Any] | None:
    return store.find(MODULE, entry_id)


def find_by_code(batch_code: str) -> dict[str, Any] | None:
    return _find_batch(batch_code)


def export_payload(*, scope: str | None = None, only_abnormal: bool = False) -> dict[str, Any]:
    """导出异常指标批次：保留批次编号、阈值快照和证据明细。"""
    rows = list(store.rows(MODULE))
    if scope:
        rows = [row for row in rows if row.get("范围类型") == scope]
    if only_abnormal:
        rows = [row for row in rows if row.get("异常")]
    rows = sorted(rows, key=lambda row: (str(row.get("指标编号") or ""), str(row.get("窗口起") or "")))
    return {
        "module": "monitor_batch",
        "exported_at": format_time(utc_now()),
        "scope": scope or "全部",
        "only_abnormal": only_abnormal,
        "total": len(rows),
        "items": [_evidence_row(row) for row in rows],
    }


def export_json_bytes(*, scope: str | None = None, only_abnormal: bool = False) -> bytes:
    payload = export_payload(scope=scope, only_abnormal=only_abnormal)
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def export_csv_bytes(*, scope: str | None = None, only_abnormal: bool = False) -> bytes:
    payload = export_payload(scope=scope, only_abnormal=only_abnormal)
    fields = [
        "批次编号",
        "指标编号",
        "契约编号",
        "窗口起",
        "窗口止",
        "时间窗分钟",
        "阈值版本",
        "日志数",
        "错误数",
        "错误率",
        "QPS",
        "最大耗时",
        "异常",
        "异常原因",
        "范围类型",
        "截止边界",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in payload["items"]:
        writer.writerow({field: item.get(field) for field in fields})
    return buffer.getvalue().encode("utf-8-sig")


def package_bytes(*, scope: str | None = None, only_abnormal: bool = False) -> bytes:
    """打包异常指标批次：清单 + 批次 JSON + 证据 CSV，导入后可还原同一批证据。"""
    payload = export_payload(scope=scope, only_abnormal=only_abnormal)
    manifest = {
        "module": "monitor_batch",
        "format": "monitor-batch-package/1",
        "exported_at": payload["exported_at"],
        "total": payload["total"],
        "scope": payload["scope"],
        "only_abnormal": payload["only_abnormal"],
        "files": ["manifest.json", "batches.json", "evidence.csv"],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("batches.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr("evidence.csv", export_csv_bytes(scope=scope, only_abnormal=only_abnormal))
    return buffer.getvalue()


def import_payload(payload: dict[str, Any], *, operator: str = "导入") -> dict[str, Any]:
    """导入批次证据：保留原批次编号和证据明细，重复导入不覆盖已有证据。"""
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("导入内容里没有 items 列表")
    rows = store.rows(MODULE)
    now = format_time(utc_now())
    imported: list[str] = []
    skipped: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("批次编号") or "").strip()
        if not code:
            skipped.append("缺少批次编号")
            continue
        if _find_batch(code) is not None:
            skipped.append(code)
            continue
        batch_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        row = dict(raw)
        row["id"] = batch_id
        row["批次编号"] = code
        row["证据"] = list(raw.get("证据") or [])
        row["导入标记"] = IMPORT_SOURCE
        row["导入时间"] = now
        row["导入人"] = operator
        rows.append(row)
        imported.append(code)
        monitor_contract.sync_batch_stats(str(row.get("指标编号") or ""))
    return {
        "导入批次": len(imported),
        "跳过批次": len(skipped),
        "导入编号": imported,
        "跳过编号": skipped,
        "导入时间": now,
    }


def reconcile(*, metric_code: str | None = None) -> dict[str, Any]:
    """复核指标状态、时间窗、日志范围与异常告警是否一致。"""
    _ensure_contracts()
    metrics = store.rows("monitor")
    if metric_code:
        metrics = [row for row in metrics if str(row.get("指标编号")) == metric_code]
    checks: list[dict[str, Any]] = []
    for metric in metrics:
        code = str(metric.get("指标编号") or "")
        contract = monitor_contract.find_by_metric(code)
        batches = [row for row in store.rows(MODULE) if str(row.get("指标编号")) == code and not row.get("导入标记")]
        current = [row for row in batches if row.get("范围类型") == SCOPE_CURRENT]
        history = [row for row in batches if row.get("范围类型") == SCOPE_HISTORY]
        alerts = [row for row in store.rows("monitor_alert") if str(row.get("指标编号")) == code]
        enabled = str(metric.get("status")) == "已启用"
        contract_enabled = bool(contract and contract.get("启用状态") == monitor_contract.CONTRACT_ENABLED)
        cutoff = metric.get("截止边界")
        window = parse_minutes(metric.get("时间窗分钟"), 60)
        range_start = metric.get("日志范围起")
        range_end = metric.get("日志范围止")
        issues: list[str] = []
        if enabled != contract_enabled:
            issues.append("指标状态与契约启用状态不一致")
        if contract and int(parse_number(contract.get("时间窗分钟")) or 0) != window:
            issues.append("时间窗未同步到契约")
        if contract and (contract.get("日志范围起"), contract.get("日志范围止")) != (range_start, range_end):
            issues.append("日志范围未同步到契约")
        if not enabled:
            # 只有真正启用过再停用的指标才需要截止边界；草稿/待校验尚未开始聚合。
            if not cutoff and (metric.get("生效开始") or str(metric.get("status")) == "已停用"):
                issues.append("停用指标缺少截止边界")
            for row in current:
                issues.append(f"批次 {row.get('批次编号')} 在停用后仍计入当前范围")
            for row in batches:
                if cutoff and str(row.get("截止边界") or "") != str(cutoff):
                    issues.append(f"批次 {row.get('批次编号')} 截止边界与指标不一致")
            for row in alerts:
                if row.get("范围类型") != SCOPE_HISTORY:
                    issues.append(f"告警 {row.get('告警编号')} 未转入历史范围")
        else:
            if cutoff:
                issues.append("启用指标不应保停留用前的截止边界")
        if contract and contract.get("启用状态") == monitor_contract.CONTRACT_ENABLED:
            mismatched = [row for row in alerts if row.get("范围类型") == SCOPE_CURRENT and
                          str(row.get("阈值版本")) != str(contract.get("阈值版本"))]
            if mismatched:
                issues.append("告警阈值版本与契约不一致")
        checks.append({
            "指标编号": code,
            "指标状态": metric.get("status"),
            "契约启用状态": contract.get("启用状态") if contract else None,
            "时间窗分钟": window,
            "日志范围": [range_start, range_end],
            "截止边界": cutoff,
            "当前范围批次数": len(current),
            "历史范围批次数": len(history),
            "告警数": len(alerts),
            "异常批次数": sum(1 for row in batches if row.get("异常")),
            "一致": not issues,
            "问题": issues,
        })
    return {
        "ok": all(item["一致"] for item in checks),
        "检查口径": ["指标状态", "时间窗", "日志范围", "异常告警", "指标批次"],
        "items": checks,
        "检查时间": format_time(utc_now()),
    }


def on_metric_change(metric: dict[str, Any], contract: dict[str, Any] | None, *, refresh_alerts: bool = True) -> None:
    """指标状态/阈值变化后同步批次与告警：停用时冻结批次并给出明确截止边界。"""
    code = str(metric.get("指标编号") or "")
    cutoff = metric.get("截止边界")
    if str(metric.get("status")) == "已启用":
        # 重新启用只影响之后的聚合：已有历史批次继续按原截止边界留在历史范围，
        # 不会被后来的启用动作改写证据。当前范围内的批次按最新阈值重新仲裁。
        if contract is not None:
            for row in store.rows(MODULE):
                if str(row.get("指标编号")) != code or row.get("导入标记"):
                    continue
                if row.get("范围类型") != SCOPE_CURRENT:
                    continue
                _arbitrate(row, contract, None)
                _recompute(row, utc_now())
        monitor_contract.sync_batch_stats(code)
        if refresh_alerts:
            monitor_alert.refresh_for_metric(code, contract, None)
        return
    for row in store.rows(MODULE):
        if str(row.get("指标编号")) != code or row.get("导入标记"):
            continue
        row["截止边界"] = cutoff or row.get("截止边界")
        row["范围类型"] = SCOPE_HISTORY
        row["冻结时间"] = format_time(utc_now())
    monitor_contract.sync_batch_stats(code)
    if refresh_alerts:
        monitor_alert.refresh_for_metric(code, contract, cutoff)


# --------------------------------------------------------------------------- 内部实现


def _ensure_contracts() -> None:
    monitor_contract.ensure_contracts()


def _candidate_contracts(metric_code: str | None) -> list[dict[str, Any]]:
    contracts = monitor_contract.ensure_contracts()
    if metric_code:
        return [row for row in contracts if str(row.get("指标编号")) == metric_code]
    return list(contracts)


def _consume_log(
    log: dict[str, Any], contracts: Iterable[dict[str, Any]], now: datetime
) -> tuple[str, str | None, bool]:
    log_time = parse_time(log.get("请求时间"))
    if log_time is None:
        _mark_failed(log, "请求时间无法解析，等待修正后重试")
        return LOG_FAILED, None, False
    service = str(log.get("调用服务") or "")
    record = str(log.get("记录编号") or log.get("id"))
    candidates = [row for row in contracts if _matches_source(service, row.get("日志来源") or row.get("关联服务"))]
    if not candidates:
        log["聚合状态"] = LOG_PENDING
        log["失败原因"] = None
        return "未匹配", None, False
    joined: list[str] = []
    created_any = False
    out_of_range: list[str] = []
    for contract in candidates:
        code = str(contract.get("指标编号") or "")
        if contract.get("启用状态") != monitor_contract.CONTRACT_ENABLED:
            state = str(contract.get("指标状态") or "未启用")
            boundary = contract.get("截止边界")
            detail = f"{code} {state}（截止边界 {boundary}），迟到日志不并入指标批次" if boundary else \
                f"{code} {state}，尚未形成可聚合的日志范围"
            out_of_range.append(detail)
            continue
        range_start = parse_time(contract.get("日志范围起") or contract.get("生效开始"))
        range_end = parse_time(contract.get("日志范围止") or contract.get("截止边界"))
        if range_start and log_time < range_start:
            out_of_range.append(f"{code} 日志时间早于日志范围起 {format_time(range_start)}")
            continue
        if range_end and log_time >= range_end:
            out_of_range.append(f"{code} 日志时间晚于日志范围止 {format_time(range_end)}")
            continue
        batch, note, created = _attach(contract, log_time, log, now)
        created_any = created_any or created
        joined.append(batch)
        if note:
            log.setdefault("仲裁记录", []).append(note)
    if joined:
        log["聚合状态"] = LOG_DONE
        log["指标批次"] = joined[0]
        log["失败原因"] = None
        log["聚合时间"] = format_time(now)
        return LOG_DONE, joined[0], created_any
    log["聚合状态"] = LOG_OUT_OF_RANGE
    log["指标批次"] = None
    log["失败原因"] = "；".join(_unique(out_of_range)) or "没有可用的启用指标"
    log["聚合时间"] = format_time(now)
    log["范围类型"] = SCOPE_HISTORY if out_of_range else None
    log["聚合依据"] = {
        "记录编号": record,
        "请求时间": format_time(log_time),
        "调用服务": service,
        "日志来源": sorted({str(item) for contract in candidates for item in (contract.get("日志来源") or [])}),
    }
    return LOG_OUT_OF_RANGE, None, False


def _attach(
    contract: dict[str, Any], log_time: datetime, log: dict[str, Any], now: datetime
) -> tuple[str, str | None, bool]:
    code = str(contract.get("指标编号") or "")
    window = parse_minutes(contract.get("时间窗分钟"), 60)
    start = floor_window(log_time, window)
    end = start + timedelta(minutes=window)
    batch_code, note = _resolve_batch_code(contract, start)
    batch = _find_batch(batch_code)
    created = batch is None
    if created:
        rows = store.rows(MODULE)
        batch_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        batch = {
            "id": batch_id,
            "批次编号": batch_code,
            "指标编号": code,
            "契约编号": contract.get("契约编号"),
            "契约ID": contract.get("id"),
            "窗口起": format_time(start),
            "窗口止": format_time(end),
            "时间窗分钟": window,
            "阈值版本": contract.get("阈值版本"),
            "阈值快照": monitor_contract.contract_snapshot(contract),
            "优先级": contract.get("优先级"),
            "日志来源": list(contract.get("日志来源") or []),
            "日志范围起": contract.get("日志范围起"),
            "日志范围止": contract.get("日志范围止"),
            "截止边界": contract.get("截止边界"),
            "范围类型": SCOPE_CURRENT if contract.get("启用状态") == monitor_contract.CONTRACT_ENABLED else SCOPE_HISTORY,
            "证据": [],
            "日志数": 0,
            "错误数": 0,
            "错误率": 0.0,
            "平均耗时": 0.0,
            "最大耗时": 0.0,
            "QPS": 0.0,
            "异常": False,
            "异常原因": "",
            "状态": "正常",
            "创建时间": format_time(now),
            "更新时间": format_time(now),
            "仲裁": ARBITRATION_ORDER,
            "导入标记": None,
        }
        rows.append(batch)
        note = note or f"新建批次：{code} 窗口 {format_time(start)}"
    else:
        note = _arbitrate(batch, contract, note)
    evidence = batch.setdefault("证据", [])
    log_id = log.get("id") or log.get("记录编号")
    if not any(str(item.get("日志ID")) == str(log_id) for item in evidence):
        evidence.append({
            "日志ID": log_id,
            "记录编号": log.get("记录编号"),
            "请求时间": format_time(log_time),
            "响应耗时": log.get("响应耗时"),
            "返回码": log.get("返回码"),
            "调用服务": log.get("调用服务"),
            "调用方IP": log.get("调用方IP"),
        })
    batch["更新时间"] = format_time(now)
    return batch_code, note, created


def _resolve_batch_code(contract: dict[str, Any], start: datetime) -> tuple[str, str | None]:
    """同一指标同一窗口只保留一个当前批次；已冻结/导入的批次另起编号，保留原证据。

    停用后再启用时，窗口可能重叠：历史批次继续固定原截止边界，新日志进入新的当前批次，
    两边都能凭批次编号复核，不会互相改写。
    """
    code = str(contract.get("指标编号") or "")
    rows = store.rows(MODULE)
    for row in rows:
        if str(row.get("指标编号")) != code or str(row.get("窗口起")) != format_time(start):
            continue
        if row.get("导入标记") or row.get("冻结时间") or row.get("范围类型") == SCOPE_HISTORY:
            continue
        return str(row.get("批次编号")), None
    sequence = store.next_sequence("monitor_batch", minimum=_next_code_number(rows, "批次编号", "BATC-"))
    return f"BATC-{sequence:04d}", None


def _arbitrate(batch: dict[str, Any], contract: dict[str, Any], note: str | None) -> str:
    """版本冲突仲裁：优先级高 → 阈值版本新 → 记录 id 小。"""
    # 记录 id 一律取契约行的 id，两边同一命名空间才能比较出确定的先后。
    incoming = (
        int(parse_number(contract.get("优先级")) or 0),
        int(parse_number(contract.get("阈值版本")) or 0),
        -int(contract.get("id", 0)),
    )
    existing = (
        int(parse_number(batch.get("优先级")) or 0),
        int(parse_number(batch.get("阈值版本")) or 0),
        -_contract_id_of(batch),
    )
    if str(batch.get("阈值版本")) == str(contract.get("阈值版本")) and batch.get("契约编号") == contract.get("契约编号"):
        return note or f"沿用批次 {batch.get('批次编号')} 的阈值版本 {batch.get('阈值版本')}"
    if incoming > existing:
        history = batch.setdefault("阈值历史", [])
        history.append({"阈值版本": batch.get("阈值版本"), "阈值快照": batch.get("阈值快照"), "契约编号": batch.get("契约编号")})
        batch.update({
            "契约编号": contract.get("契约编号"),
            "契约ID": contract.get("id"),
            "阈值版本": contract.get("阈值版本"),
            "阈值快照": monitor_contract.contract_snapshot(contract),
            "优先级": contract.get("优先级"),
            "时间窗分钟": parse_minutes(contract.get("时间窗分钟"), 60),
        })
        return (note or "") + f"按「{ARBITRATION_ORDER}」采用版本 {contract.get('阈值版本')}（优先级 {contract.get('优先级')}）"
    return (note or "") + f"按「{ARBITRATION_ORDER}」保留批次阈值版本 {batch.get('阈值版本')}，忽略版本 {contract.get('阈值版本')}"


def _contract_id_of(batch: dict[str, Any]) -> int:
    if batch.get("契约ID"):
        return int(batch["契约ID"])
    code = str(batch.get("契约编号") or "")
    for row in store.rows("monitor_contract"):
        if str(row.get("契约编号")) == code:
            batch["契约ID"] = row.get("id")
            return int(row.get("id") or 0)
    return 0


def _recompute(batch: dict[str, Any], now: datetime) -> None:
    evidence = batch.get("证据") or []
    count = len(evidence)
    errors = 0
    total_cost = 0.0
    max_cost = 0.0
    costs: list[float] = []
    for item in evidence:
        code = parse_number(item.get("返回码"))
        if code is None or code < 200 or code >= 400:
            errors += 1
        cost = parse_number(item.get("响应耗时"))
        if cost is not None:
            costs.append(cost)
            total_cost += cost
            max_cost = max(max_cost, cost)
    window_minutes = parse_minutes(batch.get("时间窗分钟"), 60)
    window_seconds = max(window_minutes * 60, 1)
    error_rate = round(errors * 100 / count, 2) if count else 0.0
    average = round(total_cost / len(costs), 2) if costs else 0.0
    qps = round(count / window_seconds, 4)
    snapshot = batch.get("阈值快照") or {}
    reasons: list[str] = []
    latency_limit = parse_number(snapshot.get("延迟阈值"))
    error_limit = parse_number(snapshot.get("错误率阈值"))
    qps_limit = parse_number(snapshot.get("QPS阈值"))
    if latency_limit is not None and max_cost > latency_limit:
        reasons.append(f"最大耗时 {max_cost}ms 超过延迟阈值 {latency_limit}ms")
    if error_limit is not None and error_rate > error_limit:
        reasons.append(f"错误率 {error_rate}% 超过错误率阈值 {error_limit}%")
    if qps_limit is not None and qps > qps_limit:
        reasons.append(f"QPS {qps} 超过 QPS阈值 {qps_limit}")
    batch.update({
        "日志数": count,
        "错误数": errors,
        "错误率": error_rate,
        "平均耗时": average,
        "最大耗时": max_cost,
        "QPS": qps,
        "异常": bool(reasons),
        "异常原因": "；".join(reasons),
        "状态": "异常" if reasons else "正常",
        "日志范围止": batch.get("截止边界") or batch.get("日志范围止"),
        "更新时间": format_time(now),
    })
    contract = monitor_contract.find_by_metric(str(batch.get("指标编号")))
    if contract is not None:
        monitor_alert.upsert_for_batch(batch, contract)


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _matches_source(service: str, sources: object) -> bool:
    if not service:
        return False
    items = sources if isinstance(sources, (list, tuple)) else [sources]
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        if token == service or token in service or service in token:
            return True
    return False


def _next_code_number(rows: Iterable[dict[str, Any]], field: str, prefix: str) -> int:
    numbers = []
    for row in rows:
        text = str(row.get(field) or "")
        if text.startswith(prefix):
            try:
                numbers.append(int(text[len(prefix):]))
            except ValueError:
                continue
    return max(numbers, default=0) + 1


def _find_batch(batch_code: str) -> dict[str, Any] | None:
    for row in store.rows(MODULE):
        if str(row.get("批次编号")) == str(batch_code):
            return row
    return None


def _mark_failed(log: dict[str, Any], reason: str) -> None:
    log["聚合状态"] = LOG_FAILED
    log["失败原因"] = reason
    log["重试次数"] = int(log.get("重试次数") or 0)


def _batch_brief(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "批次编号": batch.get("批次编号"),
        "指标编号": batch.get("指标编号"),
        "窗口起": batch.get("窗口起"),
        "窗口止": batch.get("窗口止"),
        "日志数": batch.get("日志数"),
        "异常": batch.get("异常"),
        "范围类型": batch.get("范围类型"),
        "截止边界": batch.get("截止边界"),
        "阈值版本": batch.get("阈值版本"),
    }


def _evidence_row(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "批次编号": batch.get("批次编号"),
        "指标编号": batch.get("指标编号"),
        "契约编号": batch.get("契约编号"),
        "窗口起": batch.get("窗口起"),
        "窗口止": batch.get("窗口止"),
        "时间窗分钟": batch.get("时间窗分钟"),
        "阈值版本": batch.get("阈值版本"),
        "阈值快照": batch.get("阈值快照"),
        "优先级": batch.get("优先级"),
        "日志来源": batch.get("日志来源"),
        "日志范围起": batch.get("日志范围起"),
        "日志范围止": batch.get("日志范围止"),
        "截止边界": batch.get("截止边界"),
        "范围类型": batch.get("范围类型"),
        "日志数": batch.get("日志数"),
        "错误数": batch.get("错误数"),
        "错误率": batch.get("错误率"),
        "平均耗时": batch.get("平均耗时"),
        "最大耗时": batch.get("最大耗时"),
        "QPS": batch.get("QPS"),
        "异常": batch.get("异常"),
        "异常原因": batch.get("异常原因"),
        "状态": batch.get("状态"),
        "仲裁": batch.get("仲裁"),
        "证据": list(batch.get("证据") or []),
        "导入标记": batch.get("导入标记"),
    }

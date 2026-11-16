"""服务监控接口：维护监控指标，覆盖提交校验、启用监控、停用监控等动作。

变更阈值走 ``PATCH /api/monitor/{entry_id}``；聚合、重试、复核和批次查询也挂在本模块下，
便于从指标列表直接复核「指标状态 → 时间窗 → 日志范围 → 指标批次」这条链路。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import monitor_batch, monitor_contract
from app.services.monitor import MonitorService

router = APIRouter(prefix="/api/monitor", tags=["服务监控"])

service = MonitorService()

LIST_FIELDS = ["指标编号", "关联服务", "QPS阈值", "延迟阈值", "错误率阈值", "告警级别", "通知渠道", "静默分钟"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按指标编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按指标编号与状态过滤服务监控列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


def _reject_message(missing: list[str]) -> str:
    """校验失败可能是「缺字段」也可能是「字段值非法」，分开表述。"""
    if len(missing) == 1 and ("必须是数字" in missing[0] or "已存在" in missing[0]):
        return missing[0]
    if all("缺少必填字段" not in item for item in missing):
        return f"缺少必填字段：{'、'.join(missing)}"
    return "；".join(missing)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条监控指标，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.fields())
    if missing:
        return ActionResult(ok=False, message=_reject_message(missing))
    return ActionResult(ok=True, message="监控指标已登记", entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出服务监控清单：返回全量数据，供核对阈值与状态。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "monitor", "total": total, "items": items}


@router.get("/batches")
def list_batches(
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    scope: str | None = Query(default=None, description="当前、历史"),
    abnormal: str | None = Query(default=None, description="是否只看异常批次"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """指标批次列表：可从批次反查指标状态、日志范围和异常告警。"""
    items, total = monitor_batch.list_entries(
        metric_code=metric_code, scope=scope, abnormal=abnormal, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/aggregate", response_model=ActionResult)
def aggregate(payload: EntryPayload) -> ActionResult:
    """按指标状态与时间窗聚合调用日志，生成或更新指标批次。"""
    values = payload.fields()
    metric_code = str(values.get("指标编号") or "").strip() or None
    summary = monitor_batch.aggregate(metric_code=metric_code, operator=str(values.get("operator") or "值班管理员"))
    return ActionResult(ok=True, message=f"聚合完成：处理 {summary['处理日志']} 条日志，更新 {summary['更新批次']} 个批次", entry=summary)


@router.post("/retry", response_model=ActionResult)
def retry(payload: EntryPayload) -> ActionResult:
    """中断后从失败记录接着重试，只消费「失败」状态的日志。"""
    values = payload.fields()
    metric_code = str(values.get("指标编号") or "").strip() or None
    result = monitor_batch.retry_failed(metric_code=metric_code, operator=str(values.get("operator") or "值班管理员"))
    return ActionResult(ok=True, message=f"已重试 {len(result['重试记录'])} 条失败日志", entry=result)


@router.get("/reconcile")
def reconcile(metric_code: str | None = Query(default=None, description="只复核指定指标")) -> dict[str, Any]:
    """复核指标状态、时间窗、日志范围、异常告警与指标批次是否一致。"""
    return monitor_batch.reconcile(metric_code=metric_code)


@router.get("/contracts", response_model=PageResult[dict])
def list_contracts(
    metric_code: str | None = Query(default=None),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """监控指标契约列表：异常告警只读取启用状态为「启用」的契约。"""
    items, total = monitor_contract.list_entries(metric_code=metric_code, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}/batches", response_model=PageResult[dict])
def list_entry_batches(entry_id: int, page: int = 1, size: int = 20) -> PageResult[dict]:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"监控指标 {entry_id} 不存在或已归档")
    items, total = monitor_batch.list_entries(metric_code=str(entry.get("指标编号")), page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条监控指标明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"监控指标 {entry_id} 不存在或已归档")
    return entry


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改阈值类字段：阈值版本递增，契约、批次与告警同步刷新。"""
    entry, message = service.update_entry(entry_id, payload.fields())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条监控指标执行提交校验、启用监控、停用监控；不允许的动作会被拦下并说明原因。"""
    action = payload.action()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

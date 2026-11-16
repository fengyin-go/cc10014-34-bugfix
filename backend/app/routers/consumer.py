"""消费方登记接口：维护消费应用，覆盖提交审批、开通授权、撤销授权等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.consumer import ConsumerService

router = APIRouter(prefix="/api/consumer", tags=["消费方登记"])

service = ConsumerService()

LIST_FIELDS = ["应用编号", "应用名称", "订阅服务", "调用频率", "最大QPS", "联系人", "到期日期", "状态"]
STATUSES = ["草稿", "待审批", "已授权", "已取消"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按应用编号检索"),
    status: str | None = Query(default=None, description="草稿、待审批、已授权、已取消"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按应用编号与状态过滤消费方登记列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条消费应用明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"消费应用 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条消费应用，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.fields())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="消费应用已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条消费应用执行提交审批、开通授权、撤销授权；不允许的动作会被拦下并说明原因。"""
    action = payload.action()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出消费方登记清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "consumer", "total": total, "items": items}

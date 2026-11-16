"""接口文档接口：维护接口定义，覆盖提交审核、发布文档、废弃文档等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.schema import SchemaService

router = APIRouter(prefix="/api/schema", tags=["接口文档"])

service = SchemaService()

LIST_FIELDS = ["定义编号", "关联服务", "请求方法", "参数列表", "响应示例", "错误码说明", "调用示例", "文档版本"]
STATUSES = ["草稿", "待审核", "已发布", "已废弃"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按定义编号检索"),
    status: str | None = Query(default=None, description="草稿、待审核、已发布、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按定义编号与状态过滤接口文档列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条接口定义明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接口定义 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条接口定义，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.fields())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="接口定义已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条接口定义执行提交审核、发布文档、废弃文档；不允许的动作会被拦下并说明原因。"""
    action = payload.action()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出接口文档清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "schema", "total": total, "items": items}

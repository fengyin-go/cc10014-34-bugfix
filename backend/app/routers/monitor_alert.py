"""异常告警接口：只读取监控指标契约里的启用口径。

列表默认只看「当前」范围；指标停用后告警自动转入历史范围，详情里仍能看到当时的
阈值快照和截止边界，不会出现「阈值对不上、停用状态残留」的情况。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import PageResult
from app.services import monitor_alert

router = APIRouter(prefix="/api/monitor-alert", tags=["异常告警"])


@router.get("", response_model=PageResult[dict])
def list_entries(
    scope: str | None = Query(default="当前", description="当前、历史、全部"),
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    status: str | None = Query(default=None, description="活跃、历史、已恢复"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """异常告警列表：默认只返回当前启用指标产生的告警。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = monitor_alert.list_entries(
        scope=scope, metric_code=metric_code, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """告警详情：当前阈值来自契约，历史阈值来自批次快照。"""
    entry = monitor_alert.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"异常告警 {entry_id} 不存在或已归档")
    return entry

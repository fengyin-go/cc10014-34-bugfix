"""指标批次接口：查询、复核、导出/下载/打包与导入。

异常批次的导出会带上阈值快照和逐条日志证据；导入后保留原批次编号与证据，
因此「同一批指标证据」在导出前后可逐条对照。
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import monitor_batch

router = APIRouter(prefix="/api/monitor-batch", tags=["指标批次"])


@router.get("", response_model=PageResult[dict])
def list_batches(
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    scope: str | None = Query(default=None, description="当前、历史"),
    abnormal: str | None = Query(default=None, description="是否只看异常批次"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """指标批次列表：停用后原批次转历史范围并保留截止边界。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = monitor_batch.list_entries(
        metric_code=metric_code, scope=scope, abnormal=abnormal, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/reconcile")
def reconcile(metric_code: str | None = Query(default=None)) -> dict[str, Any]:
    """从批次侧复核指标状态、日志范围与异常告警是否一致。"""
    return monitor_batch.reconcile(metric_code=metric_code)


@router.get("/export")
def export_batches(
    scope: str | None = Query(default=None, description="当前、历史"),
    only_abnormal: bool = Query(default=False, description="只导出异常批次"),
    format: str = Query(default="json", description="json、csv、zip"),
) -> Any:
    """导出异常指标批次：json 是证据文件，csv 便于比对，zip 是可直接下载的打包。"""
    fmt = (format or "json").lower()
    if fmt == "json":
        return monitor_batch.export_payload(scope=scope, only_abnormal=only_abnormal)
    if fmt == "csv":
        content = monitor_batch.export_csv_bytes(scope=scope, only_abnormal=only_abnormal)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=monitor-batches.csv"},
        )
    if fmt == "zip":
        content = monitor_batch.package_bytes(scope=scope, only_abnormal=only_abnormal)
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=monitor-batches.zip"},
        )
    raise HTTPException(status_code=400, detail="导出格式只支持 json、csv、zip")


@router.post("/import", response_model=ActionResult)
def import_batches(payload: EntryPayload) -> ActionResult:
    """导入批次证据：支持 items 列表或 base64 打包文件，重复批次保留原证据不覆盖。"""
    values = payload.fields()
    items: Any = values.get("items")
    if items is None and values.get("package"):
        try:
            raw = base64.b64decode(str(values["package"]))
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                items = json.loads(archive.read("batches.json").decode("utf-8")).get("items", [])
        except (binascii.Error, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            return ActionResult(ok=False, message=f"导入包无法解析：{error}")
    if items is None and isinstance(values.get("payload"), dict):
        items = values["payload"].get("items", [])
    if not isinstance(items, list):
        return ActionResult(ok=False, message="导入内容需要 items 列表或 package 打包文件")
    result = monitor_batch.import_payload({"items": items}, operator=str(values.get("operator") or "值班管理员"))
    return ActionResult(ok=True, message=f"已导入 {result['导入批次']} 个批次，跳过 {result['跳过批次']} 个", entry=result)


@router.get("/code/{batch_code}", response_model=dict)
def get_batch_by_code(batch_code: str) -> dict[str, Any]:
    batch = monitor_batch.find_by_code(batch_code)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"指标批次 {batch_code} 不存在或已归档")
    return batch


@router.get("/{entry_id}", response_model=dict)
def get_batch(entry_id: int) -> dict[str, Any]:
    """读取单个指标批次，含阈值快照、异常判断依据和逐条日志证据。"""
    batch = monitor_batch.get_entry(entry_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"指标批次 {entry_id} 不存在或已归档")
    return batch

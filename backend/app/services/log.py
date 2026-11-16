"""调用日志业务规则：状态流转、字段校验与筛选口径都收在这里。

日志写入后立即参与指标批次聚合：只有启用指标、且请求时间落在该指标的日志范围内，
才会被计入批次；停用后迟到的日志保持「超范围」，不会把批次撑大。
"""
from __future__ import annotations

from typing import Any

from app.services.timeutil import format_time, parse_time, utc_now
from app.store import store

MODULE = "log"
REQUIRED_FIELDS = ["记录编号", "调用服务", "请求时间"]
OPTIONAL_FIELDS = ["响应耗时", "返回码", "调用方IP", "请求大小KB", "响应大小KB"]
STATUS_ORDER = ["草稿", "记录中", "已归档", "已清理"]
ACTION_RULES = {"归档记录": "已归档", "清理日志": "已清理", "导出日志": "已归档"}
NEGATIVE_ACTIONS = []
LOG_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


class LogService:
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
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        if parse_time(values.get("请求时间")) is None:
            return None, ["请求时间无法解析，请使用 YYYY-MM-DD HH:MM:SS"]
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LOG_FIELDS if field in values})
        entry["status"] = str(values.get("status") or STATUS_ORDER[0])
        if entry["status"] not in STATUS_ORDER:
            entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["聚合状态"] = "待聚合"
        entry["指标批次"] = None
        entry["失败原因"] = None
        entry["写入时间"] = format_time(utc_now())
        rows.append(entry)
        self.aggregate_pending()
        return entry, []

    def aggregate_pending(self) -> dict[str, Any]:
        """单条日志写入后立即尝试聚合，失败原因留在日志上供重试。"""
        from app.services import monitor_batch

        return monitor_batch.aggregate(operator="调用日志写入")

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"日志记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于调用日志可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"日志记录已{action}"

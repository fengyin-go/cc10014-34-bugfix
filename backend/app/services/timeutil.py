"""时间口径工具：监控指标与调用日志都按同一套解析、格式化和窗口切分规则处理。

示例数据里的「请求时间」既有日期也有带时分秒的时间串，这里统一成不带时区的
``datetime``，避免因为本地时区不同把同一批日志切到两个窗口里。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_TIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
)

_MULTIPLIER = {"秒": 1 / 60, "s": 1 / 60, "分": 1, "m": 1, "分钟": 1, "时": 60, "h": 60, "小时": 60}


def utc_now() -> datetime:
    """当前时间（不带时区），与示例数据口径保持一致。"""
    return datetime.now().replace(microsecond=0)


def parse_time(value: object) -> datetime | None:
    """把日志/版本里的时间字段解析成 ``datetime``；解析不了返回 ``None``。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, microsecond=0)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None, microsecond=0)
    except ValueError:
        pass
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def format_time(value: datetime | None) -> str | None:
    """统一输出到秒，便于批次截止边界做字符串比较。"""
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def parse_minutes(value: object, default: int = 5) -> int:
    """解析时间窗：支持数字、``5m``、``1h``、``5 分钟`` 等写法。"""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return max(int(value), 1)
    text = str(value).strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([^\d\s]*)", text)
    if not match:
        return default
    size = float(match.group(1))
    unit = match.group(2) or "分钟"
    multiplier = _MULTIPLIER.get(unit, 1)
    return max(int(size * multiplier), 1)


def parse_number(value: object) -> float | None:
    """阈值/耗时字段转数字；示例数据里的占位文案返回 ``None``。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def floor_window(moment: datetime, minutes: int) -> datetime:
    """按分钟数向下取整到窗口起点。"""
    minutes = max(minutes, 1)
    epoch = datetime(1970, 1, 1)
    elapsed = int((moment - epoch).total_seconds())
    bucket = elapsed - (elapsed % (minutes * 60))
    return epoch + timedelta(seconds=bucket)

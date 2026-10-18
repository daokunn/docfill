"""日期解析与输出格式化。

设计原则：
- 解析、存储、表达式计算统一使用 ISO 风格（YYYY-MM-DD），保证可比较、可计算。
- 只在“写入文档前”按用户设置的格式输出，避免影响 substr 等表达式。
- 无法识别为日期的值原样返回，绝不猜测。
"""

import datetime
import re
from typing import Any, Dict, Optional, Tuple

DEFAULT_DATE_FORMAT = "YYYY年M月D日"
DEFAULT_RANGE_SEPARATOR = "至"

DATE_FORMAT_PRESETS = [
    "YYYY年M月D日",
    "YYYY年MM月DD日",
    "YYYY-MM-DD",
    "YYYY/MM/DD",
    "YYYYMMDD",
    "M月D日",
]

RANGE_SEPARATOR_PRESETS = ["至", "到", "~", "—"]

# 字段名包含这些关键词时，视为日期/时间字段
_DATE_FIELD_KEYWORDS = (
    "日期",
    "时间",
    "出生",
    "生日",
    "起始",
    "截止",
    "起止",
    "有效期",
    "到期",
    "签发",
)

_RANGE_SPLIT = re.compile(r"\s*(?:~|至|到|—|–)\s*")


def parse_date_value(value: Any) -> Optional[datetime.date]:
    """把常见日期写法解析为 date；失败返回 None。

    支持：20260101 / 2026-01-01 / 2026/1/1 / 2026.1.1 / 2026年1月1日
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # 8 位纯数字
    if re.fullmatch(r"\d{8}", text):
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:8])
        return _build_date(year, month, day)

    # 2026-01-01 / 2026/1/1 / 2026.1.1
    match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        return _build_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    # 2026年1月1日 / 2026年1月1
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if match:
        return _build_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    return None


def _build_date(year: int, month: int, day: int) -> Optional[datetime.date]:
    """构造并校验日期，非法日期返回 None。"""
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def format_date(value: Any, pattern: Optional[str] = None) -> str:
    """把日期按 pattern 格式化；不是日期则原样返回字符串。

    支持的占位符：YYYY、YY、MM、M、DD、D
    """
    date_value = parse_date_value(value)
    if date_value is None:
        return str(value) if value is not None else ""

    pattern = (pattern or DEFAULT_DATE_FORMAT).strip() or DEFAULT_DATE_FORMAT

    replacements = [
        ("YYYY", f"{date_value.year:04d}"),
        ("YY", f"{date_value.year % 100:02d}"),
        ("MM", f"{date_value.month:02d}"),
        ("M", str(date_value.month)),
        ("DD", f"{date_value.day:02d}"),
        ("D", str(date_value.day)),
    ]
    for token, replacement in replacements:
        pattern = pattern.replace(token, replacement)
    return pattern


def is_date_field(field_name: str) -> bool:
    """按字段名判断是否属于日期/时间字段。"""
    name = str(field_name or "")
    return any(keyword in name for keyword in _DATE_FIELD_KEYWORDS)


def is_range_field(field_name: str) -> bool:
    """是否为起止/范围类字段。"""
    name = str(field_name or "")
    return "起止" in name or "期间" in name or "范围" in name


def split_date_range(value: Any) -> Optional[Tuple[str, str]]:
    """拆分日期范围；不是两段则返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = _RANGE_SPLIT.split(text)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def format_output_values(
    values: Dict[str, Any],
    date_format: Optional[str] = None,
    range_separator: Optional[str] = None,
) -> Dict[str, Any]:
    """在写入文档前格式化日期字段，返回新的字典。

    只处理“字段名像日期”的字段，避免把项目编号等 8 位数字误判成日期。
    """
    if date_format is None or range_separator is None:
        from config.settings import get_settings

        settings = get_settings()
        if date_format is None:
            date_format = str(settings.get("date_format", DEFAULT_DATE_FORMAT))
        if range_separator is None:
            range_separator = str(settings.get("date_range_separator", DEFAULT_RANGE_SEPARATOR))

    date_format = (date_format or DEFAULT_DATE_FORMAT).strip() or DEFAULT_DATE_FORMAT
    range_separator = (range_separator or DEFAULT_RANGE_SEPARATOR).strip() or DEFAULT_RANGE_SEPARATOR

    result = dict(values)
    for name, raw_value in values.items():
        if not is_date_field(name):
            continue
        if raw_value is None:
            continue

        parts = None
        if is_range_field(name) or isinstance(raw_value, str):
            parts = split_date_range(raw_value)

        if parts:
            start, end = parts
            start_date = parse_date_value(start)
            end_date = parse_date_value(end)
            if start_date and end_date:
                result[name] = f"{format_date(start_date, date_format)}{range_separator}{format_date(end_date, date_format)}"
                continue

        result[name] = format_date(raw_value, date_format)

    return result


def preview_date_format(
    pattern: Optional[str] = None,
    range_separator: Optional[str] = None,
) -> str:
    """给设置界面用的实时预览。"""
    pattern = (pattern or DEFAULT_DATE_FORMAT).strip() or DEFAULT_DATE_FORMAT
    separator = (range_separator or DEFAULT_RANGE_SEPARATOR).strip() or DEFAULT_RANGE_SEPARATOR
    start = datetime.date(2026, 1, 1)
    end = datetime.date(2026, 3, 30)
    return f"{format_date(start, pattern)}{separator}{format_date(end, pattern)}"

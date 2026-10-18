"""CSV 读取与预览辅助：处理中文 Windows 常见的编码差异。"""

import csv
import io
from typing import List, Tuple

# 优先 UTF-8，再尝试中文 Windows 常见的 GB18030
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "utf-16")

HEADER_NAMES = {"变量名", "字段", "字段名", "名称", "field", "name", "key"}
VALUE_NAMES = {"值", "变量值", "内容", "value"}


def read_csv_file(path: str) -> Tuple[str, str]:
    """读取 CSV 文本，返回 (text, encoding)。"""
    with open(path, "rb") as handle:
        raw = handle.read()

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"

    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # 最后兜底：不因为少量坏字符拒绝整个文件
    return raw.decode("utf-8", errors="replace"), "utf-8/replace"


def parse_csv_rows(text: str) -> List[List[str]]:
    """把 CSV 文本解析为二维列表，自动忽略完全空白的行。"""
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if any(str(cell).strip() for cell in row):
            rows.append([str(cell).strip() for cell in row])
    return rows


def detect_header(rows: List[List[str]]) -> bool:
    """根据首行内容判断是否有表头。"""
    if not rows:
        return False
    first = [cell.strip().lower() for cell in rows[0]]
    if len(first) >= 2 and first[0] in HEADER_NAMES and first[1] in VALUE_NAMES:
        return True
    return first[0] in HEADER_NAMES


def rows_to_mapping(rows: List[List[str]], has_header: bool = False) -> dict:
    """把二维行转换为 {变量名: 值}；值列有多列时用逗号连接。"""
    mapping = {}
    start = 1 if has_header else 0
    for row in rows[start:]:
        if len(row) < 2:
            continue
        name = str(row[0]).strip()
        if not name:
            continue
        value = ",".join(str(cell).strip() for cell in row[1:]).strip()
        mapping[name] = value
    return mapping

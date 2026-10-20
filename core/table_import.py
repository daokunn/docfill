"""宽表读取：第一行是变量标题，接下来每行是一个人的数据。

这是名单导入的数据来源。和旧的 core/csv_io.py 区别在于：
  - csv_io 是「变量名,值」两列竖排，一个文件只能装一个人
  - 本模块是横排宽表，一个文件装一批人

支持 .xlsx / .xls / .csv。表头列名会自动走一遍别名映射，
所以系统导出的「证件号码」能对上模板里的「身份证号」。
"""

import csv
import io
import os
import re
from typing import Dict, List, Optional, Tuple

# 复用 csv_io 里已经处理好的中文编码兼容（GB18030 / UTF-16 / BOM）
from core.csv_io import ENCODINGS

TEMPLATE_EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".txt")

# 导入预览最多展示多少行，防止几千行的文件把界面拖死
MAX_PREVIEW_ROWS = 200


class TableImportError(Exception):
    """宽表读取失败。"""


def read_table_file(path: str) -> Tuple[List[str], List[List[str]], str, List[str]]:
    """读取宽表文件，返回 (表头列名, 数据行, 文件类型说明, 警告列表)。

    警告列表用于提示 Excel 数字精度丢失等"读到了但值不可信"的情况，
    由界面展示给用户，不阻断导入。

    :raises TableImportError: 文件不存在、格式不支持或内容为空
    """
    if not path or not os.path.exists(path):
        raise TableImportError("文件不存在，请重新选择。")

    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext in (".csv", ".txt"):
        return _read_csv_like(path)
    raise TableImportError(
        f"不支持的文件类型「{ext}」。请用 .xlsx 或 .csv（Excel 里另存为即可）。")


def _read_xlsx(path: str) -> Tuple[List[str], List[List[str]], str, List[str]]:
    """读取 Excel 宽表。"""
    try:
        import openpyxl
    except ImportError:
        raise TableImportError("缺少 openpyxl，无法读取 Excel 文件。请先安装依赖。")

    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise TableImportError(f"Excel 打开失败：{exc}")

    try:
        sheets = workbook.worksheets
        if not sheets:
            raise TableImportError("Excel 里没有工作表。")

        # 取第一个非空工作表：用户的名单有时不在第一个 sheet
        sheet = _pick_first_non_empty(sheets)
        header, rows, warnings = _extract_sheet_rows(sheet)
        note = f"工作表「{sheet.title}」" if len(sheets) > 1 else "Excel"
    finally:
        try:
            workbook.close()
        except Exception:
            pass

    if not header:
        raise TableImportError("没有读到表头行，请确认第一行是变量标题。")
    if not rows:
        raise TableImportError("只有表头没有数据行。")
    return header, rows, note, warnings


def _pick_first_non_empty(sheets) -> object:
    """返回第一个有数据的工作表，全空则返回第一个。"""
    for sheet in sheets:
        for row in sheet.iter_rows(values_only=True):
            if any(_cell_text(value) for value in row):
                return sheet
    return sheets[0]


def _extract_sheet_rows(sheet) -> Tuple[List[str], List[List[str]], List[str]]:
    """从工作表提取表头、数据行和精度警告，跳过完全空白的行。"""
    header: List[str] = []
    rows: List[List[str]] = []
    warnings: List[str] = []
    # 已经警告过的列，避免 100 行刷出 100 条同样的提示
    warned_columns: set = set()

    for raw_row in sheet.iter_rows(values_only=True):
        if not header:
            header = [_cell_text(value) for value in raw_row]
            if not any(header):
                continue
            continue

        cells = []
        for index, value in enumerate(raw_row):
            cells.append(_cell_text(value))
            if _is_precision_loss(value):
                column = header[index] if index < len(header) else f"第{index + 1}列"
                if column not in warned_columns:
                    warned_columns.add(column)
                    warnings.append(_precision_warning(column))
        if not any(cells):
            continue
        rows.append(cells)

    # 去掉表头尾部多余的空列名
    while header and not header[-1]:
        header.pop()
    width = len(header)
    rows = [row[:width] for row in rows]
    return header, rows, warnings


# float64 能精确表示的最大整数。超过这个值的数字存进 Excel 数字单元格，
# 尾部几位在文件里就已经永久丢失，软件读到的不是用户原本输入的值。
_FLOAT64_SAFE_INTEGER = 2 ** 53


def _is_precision_loss(value) -> bool:
    """判断单元格值是否已经因 Excel 数字精度丢失而不可信。

    典型场景：18 位身份证号被存成"数值"而不是"文本"。
    Excel 只能保留 15 位有效数字，360700199001011234 会变成
    360700199001011000 这种，末尾几位是错的，而且看不出来。
    """
    if isinstance(value, bool) or value is None:
        return False
    if not isinstance(value, (int, float)):
        return False
    try:
        return abs(float(value)) > _FLOAT64_SAFE_INTEGER
    except (TypeError, ValueError, OverflowError):
        return False


def _precision_warning(column: str) -> str:
    """生成精度丢失的警告文案。"""
    return (
        f"列「{column}」里有超过 15 位的数字（如身份证号、银行卡号），"
        f"在 Excel 中被存成了「数值」格式，末尾几位已经丢失，读到的不是原始值。\n"
        f"    解决办法：在 Excel 里把该列的单元格格式改成「文本」，"
        f"然后重新输入这些号码（改格式不会自动恢复已丢失的数字），再重新导入。"
    )


def _cell_text(value) -> str:
    """把单元格值转成干净的字符串。

    Excel 里的数字会变成 12345.0 这种浮点尾巴，日期会变成 datetime，
    都要处理掉，否则身份证号导入后会多出 .0。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        # 整数值不要带小数点：360700199001011234.0 -> 360700199001011234
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)

    # 日期时间：只保留到日，避免带上 00:00:00
    try:
        import datetime
        if isinstance(value, datetime.datetime):
            if value.hour or value.minute or value.second:
                return value.strftime("%Y-%m-%d %H:%M:%S")
            return value.strftime("%Y-%m-%d")
        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")
    except ImportError:
        pass

    return str(value).strip()


def _read_csv_like(path: str) -> Tuple[List[str], List[List[str]], str, List[str]]:
    """读取 CSV/TXT 宽表，自动尝试常见中文编码。"""
    with open(path, "rb") as handle:
        raw = handle.read()

    text: Optional[str] = None
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        for encoding in ENCODINGS:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    # Excel 导出的 CSV 可能用分号或制表符分隔
    delimiter = _guess_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    header: List[str] = []
    rows: List[List[str]] = []
    warnings: List[str] = []
    warned_columns: set = set()

    for raw_row in reader:
        cells = [str(cell).strip() for cell in raw_row]
        if not any(cells):
            continue
        if not header:
            header = cells
            continue

        for index, value in enumerate(cells):
            if _is_scientific_notation(value):
                column = header[index] if index < len(header) else f"第{index + 1}列"
                if column not in warned_columns:
                    warned_columns.add(column)
                    warnings.append(_scientific_notation_warning(column, value))
        rows.append(cells)

    while header and not header[-1]:
        header.pop()
    width = len(header)
    rows = [row[:width] for row in rows]

    if not header:
        raise TableImportError("没有读到表头行，请确认第一行是变量标题。")
    if not rows:
        raise TableImportError("只有表头没有数据行。")
    return header, rows, f"CSV（{delimiter_name(delimiter)}分隔）", warnings


# Excel 把长数字存进 CSV 时会写成科学计数法，原始号码已经丢失
_SCIENTIFIC_NOTATION = re.compile(r"^[-+]?\d+(?:\.\d+)?[eE][-+]?\d+$")


def _is_scientific_notation(value: str) -> bool:
    """判断值是否是科学计数法形式的长数字（如 3.60700E+17）。"""
    return bool(_SCIENTIFIC_NOTATION.match(str(value or "").strip()))


def _scientific_notation_warning(column: str, sample: str) -> str:
    """生成科学计数法损坏的警告文案。"""
    return (
        f"列「{column}」里有科学计数法形式的值（如 {sample}），"
        f"这通常是用 Excel 打开 CSV 后又另存造成的，原始号码已经丢失。\n"
        f"    解决办法：从原始数据源重新导出 CSV，"
        f"或在 Excel 里把该列格式设为「文本」后重新输入。"
    )


def _guess_delimiter(text: str) -> str:
    """从前几行猜分隔符：逗号、制表符、分号里选出现最稳定的那个。"""
    sample_lines = [line for line in text.splitlines()[:5] if line.strip()]
    if not sample_lines:
        return ","

    best = ","
    best_score = -1
    for candidate in (",", "\t", ";"):
        counts = [line.count(candidate) for line in sample_lines]
        if not counts or counts[0] == 0:
            continue
        # 每行分隔符数量一致才算可靠（表头和数据列数应当相同）
        consistent = all(count == counts[0] for count in counts)
        score = counts[0] * (2 if consistent else 1)
        if score > best_score:
            best_score = score
            best = candidate
    return best


def delimiter_name(delimiter: str) -> str:
    """分隔符的中文名，用于界面提示。"""
    return {",": "逗号", "\t": "制表符", ";": "分号"}.get(delimiter, delimiter)


def rows_to_dicts(header: List[str], rows: List[List[str]]) -> List[Dict[str, str]]:
    """把表头 + 数据行转成 [{列名: 值}]，这是名单合并要的输入形状。"""
    output: List[Dict[str, str]] = []
    for row in rows:
        item: Dict[str, str] = {}
        for index, name in enumerate(header):
            name = str(name).strip()
            if not name:
                continue
            value = row[index].strip() if index < len(row) else ""
            # 同一列名重复出现时，保留第一个非空值
            if name in item and item[name]:
                continue
            item[name] = value
        if any(str(value).strip() for value in item.values()):
            output.append(item)
    return output


def map_header_to_variables(header: List[str], template_vars: List[str],
                            normalize=None) -> Dict[str, str]:
    """把文件表头映射到模板变量名，返回 {文件列名: 模板变量名}。

    映射不到的列保持原样（作为名单里的附加列，不影响生成）。
    这样系统导出的「证件号码」能自动对上模板的「身份证号」，
    而对不上的列也不会被丢掉——用户可能要它做备注。
    """
    mapping: Dict[str, str] = {}
    known = {str(name).strip() for name in template_vars if str(name).strip()}

    for column in header:
        column = str(column).strip()
        if not column:
            continue
        if column in known:
            mapping[column] = column
            continue

        target = ""
        if normalize is not None:
            try:
                target = normalize(column, list(known))
            except Exception:
                target = ""
        mapping[column] = target or column
    return mapping


def preview_text(header: List[str], rows: List[List[str]],
                 limit: int = 8) -> str:
    """生成给用户看的预览文本。"""
    if not header:
        return "（空表）"
    lines = ["  " + " | ".join(str(name) for name in header[:8])]
    for row in rows[:limit]:
        lines.append("  " + " | ".join(str(cell) for cell in row[:8]))
    if len(rows) > limit:
        lines.append(f"  …… 另有 {len(rows) - limit} 行")
    return "\n".join(lines)

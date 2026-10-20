"""移交清单 / 汇总表：把一批人追加进一张长期累积的 Excel 台账。

场景：柜员小李录完一批客户、生成好文档后，要把这批人移交给小陈复核。
移交清单不是一次性文件，而是一张不断往下累加的台账表——今天 20 人、明天再来 30 人，
都追加到同一个 xlsx 里，交接时一眼看全。

两种模式（用户无感，程序自动判断）：
  A. 未指定汇总模板 → 用名单列名自动生成标准表头，写到输出目录下的固定台账文件。
  B. 指定了汇总模板（一个 .xlsx，第一行是表头，可含 {{变量名}} 或纯文字列名）→
     以模板表头为准；台账首次由模板复制生成，之后只往末尾追加数据行。

"追加"的实现关键：永远读已存在的台账文件、定位到最后一个非空行的下一行再写，
绝不覆盖已有内容。重复移交同一批人时按去重键匹配旧行更新，不再加新行。
"""

import datetime
import os
from typing import Dict, List, Optional, Sequence, Tuple

# 台账里额外附加的固定列（不属于业务变量，用于交接说明）
LEDGER_META_COLUMNS = ("移交时间", "经办状态")


def _openpyxl():
    try:
        import openpyxl
        return openpyxl
    except ImportError as exc:  # pragma: no cover - 依赖缺失时才触发
        raise RuntimeError("缺少 openpyxl，无法读写移交清单。请先安装依赖。") from exc


def ledger_path(output_dir: str, business_name: str) -> str:
    """台账文件的固定路径：输出根目录/移交清单_业务.xlsx。

    固定名字才能跨批次持续追加；不同业务各自一份，互不干扰。
    """
    safe = "".join(c for c in str(business_name or "未命名业务") if c not in '\\/:*?"<>|')
    return os.path.join(output_dir, f"移交清单_{safe or '未命名业务'}.xlsx")


def read_template_header(template_path: str) -> List[str]:
    """读取汇总模板第一行作为表头（去掉尾部空列）。"""
    openpyxl = _openpyxl()
    workbook = openpyxl.load_workbook(template_path, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        header: List[str] = []
        for row in sheet.iter_rows(min_row=1, max_row=1, values_only=True):
            header = [str(cell).strip() if cell is not None else "" for cell in row]
            break
    finally:
        workbook.close()
    while header and not header[-1]:
        header.pop()
    return header


def resolve_columns(header: List[str], available_vars: Sequence[str]) -> List[Tuple[str, str]]:
    """把表头列对应到名单里的实际列名。

    返回 [(表头列名, 名单列名)]；表头写了 {{姓名}} 会剥成 姓名；
    优先精确/别名匹配，都对不上时退一步用"互相包含"的模糊匹配
    （如模板写「客户姓名」而名单叫「姓名」），仍找不到就留空列不硬塞。
    """
    from core.field_mapper import match_template_variable

    available = [str(v).strip() for v in available_vars if str(v).strip()]
    resolved: List[Tuple[str, str]] = []
    for column in header:
        raw = str(column or "").strip()
        key = raw.strip("{}").strip()          # {{姓名}} -> 姓名
        matched = match_template_variable(key, available)
        if not matched:
            matched = _fuzzy_match(key, available)
        resolved.append((raw, matched or ""))
    return resolved


def _fuzzy_match(header_key: str, available: List[str]) -> str:
    """表头与名单列名的宽松匹配：一方包含另一方即认为同一列。

    只在唯一命中时才采用，避免「金额」同时像「贷款金额」「还款金额」时猜错。
    """
    if not header_key:
        return ""
    candidates = [name for name in available
                  if header_key in name or name in header_key]
    return candidates[0] if len(candidates) == 1 else ""


def append_batch(
    output_dir: str,
    business_name: str,
    people: Sequence[Dict[str, str]],
    template_path: str = "",
    dedup_field: str = "姓名",
    status_by_key: Optional[Dict[str, str]] = None,
) -> Tuple[str, int, int, List[str]]:
    """把一批人追加进台账。返回 (台账路径, 新增行数, 更新行数, 未匹配表头列)。

    :param people: [{列名: 值}]，本批每个人一条
    :param template_path: 汇总模板 xlsx（B 模式）；为空则 A 模式用名单列名建表头
    :param dedup_field: 去重键列名，命中旧行则更新而非再加一行
    :param status_by_key: {去重键值: 状态文本}，写入"经办状态"列
    :return 未匹配表头列：模板里有、但名单里找不到对应数据的列名（供界面提示）
    """
    openpyxl = _openpyxl()
    from openpyxl.styles import Alignment, Font, PatternFill

    path = ledger_path(output_dir, business_name)
    status_by_key = status_by_key or {}

    # 决定表头：B 用模板表头，A 用第一条记录的键 + 元数据列
    if template_path and os.path.exists(template_path):
        header = read_template_header(template_path)
        columns_map = resolve_columns(header, _union_keys(people))
    else:
        header = _union_keys(people) + list(LEDGER_META_COLUMNS)
        columns_map = [(name, name) for name in header]

    # 打开已有台账或新建
    exists = os.path.exists(path)
    if exists:
        workbook = openpyxl.load_workbook(path)
        sheet = workbook.active
        existing_header = [
            (str(c.value).strip() if c.value is not None else "")
            for c in sheet[1]
        ]
        # 台账已存在且表头和本次不一致：以台账为准，缺的列忽略，多的列追加到右侧
        effective_header, effective_map = _reconcile(existing_header, header, columns_map)
    else:
        os.makedirs(output_dir, exist_ok=True)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "移交清单"
        sheet.append(header)
        _style_header(sheet, len(header))
        effective_header, effective_map = header, columns_map

    # 建立 去重键值 -> 台账行号 索引（跳过表头）
    dedup_col = _find_column(effective_header, dedup_field)
    row_index_by_key: Dict[str, int] = {}
    last_row = 1
    if dedup_col:
        col_letter_idx = effective_header.index(dedup_col) + 1
        for r in range(2, sheet.max_row + 1):
            value = sheet.cell(row=r, column=col_letter_idx).value
            text = str(value).strip() if value is not None else ""
            if text:
                row_index_by_key.setdefault(text, r)
            if any(sheet.cell(row=r, column=c).value not in (None, "")
                   for c in range(1, len(effective_header) + 1)):
                last_row = max(last_row, r)

    added = updated = 0
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for person in people:
        key_value = str(person.get(dedup_field, "") or "").strip()
        target_row = row_index_by_key.get(key_value) if key_value else None
        is_new = target_row is None
        if is_new:
            target_row = last_row + 1
            last_row = target_row
            added += 1
        else:
            updated += 1

        for header_name, source_name in effective_map:
            if header_name not in effective_header:
                continue
            col = effective_header.index(header_name) + 1
            if header_name == "移交时间":
                sheet.cell(row=target_row, column=col, value=now)
                continue
            if header_name == "经办状态":
                sheet.cell(row=target_row, column=col,
                           value=status_by_key.get(key_value, "已生成"))
                continue
            value = str(person.get(source_name, "") or "") if source_name else ""
            if value:  # 只写非空，避免用空白覆盖台账里已有的值
                cell = sheet.cell(row=target_row, column=col, value=value)
                if _looks_like_long_number(header_name):
                    cell.number_format = "@"

    _autosize(sheet, len(effective_header))
    workbook.save(path)
    unmatched = [name for name, source in columns_map
                 if not source and name not in LEDGER_META_COLUMNS]
    return path, added, updated, unmatched


def _union_keys(people: Sequence[Dict[str, str]]) -> List[str]:
    keys: List[str] = []
    for person in people:
        for name in person:
            name = str(name).strip()
            if name and name not in keys:
                keys.append(name)
    return keys


def _reconcile(existing_header: List[str], new_header: List[str],
               columns_map: List[Tuple[str, str]]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """台账已有表头与本次不同时：沿用台账顺序，新出现的列补到最右。"""
    merged = [h for h in existing_header if h]
    mapping = dict(columns_map)
    for name in new_header:
        if name and name not in merged:
            merged.append(name)
    effective_map = [(name, mapping.get(name, name)) for name in merged]
    return merged, effective_map


def _find_column(header: List[str], field: str) -> Optional[str]:
    field = str(field or "").strip()
    if field in header:
        return field
    # 允许"姓名"对上带空格的表头等轻微差异
    for name in header:
        if name and name.strip() == field:
            return name
    return None


_LONG_NUMBER_HINTS = ("身份证", "证件", "卡号", "账号", "账户", "手机", "电话",
                      "编号", "号码", "流水", "社保", "公积金")


def _looks_like_long_number(column: str) -> bool:
    text = str(column or "")
    return any(hint in text for hint in _LONG_NUMBER_HINTS)


def _style_header(sheet, width: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    fill = PatternFill("solid", fgColor="FFDCE6F1")
    font = Font(bold=True, color="FF1F2937")
    for index in range(1, width + 1):
        cell = sheet.cell(row=1, column=index)
        cell.font = font
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"


def _autosize(sheet, width: int) -> None:
    from openpyxl.utils import get_column_letter
    for column_index in range(1, width + 1):
        longest = 0
        for row in sheet.iter_rows(min_col=column_index, max_col=column_index, values_only=True):
            text = str(row[0] or "")
            length = sum(2 if ord(ch) > 127 else 1 for ch in text)
            longest = max(longest, length)
        letter = get_column_letter(column_index)
        sheet.column_dimensions[letter].width = min(max(longest + 2, 10), 40)

"""
文档填充渲染模块
职责：
  接收模板路径 + 变量字典，输出填充完成的文档副本。
  只负责变量替换，不处理界面逻辑、不处理输出目录。
  原始模板文件只读，不会被修改。
"""

import os
import re
import shutil
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from core.scanner import VAR_PATTERN, split_optional_marker


class RenderError(Exception):
    """文档渲染错误"""
    pass


def _replace_in_text(text: str, variables: Dict[str, Any]) -> str:
    """将文本中的 {{变量名}} 替换为变量值"""
    def replacer(m: re.Match) -> str:
        """正则替换回调：取变量名（忽略可选标记），找不到则保留原标记"""
        raw_name = m.group(1) or m.group(2) or ""
        var_name, _optional = split_optional_marker(raw_name)
        return str(variables.get(var_name, m.group(0)))

    return VAR_PATTERN.sub(replacer, text or "")


def _replace_in_paragraph_nodes(nodes, variables: Dict[str, Any]) -> bool:
    """在同一个段落的 w:t 节点中替换变量，但不碰任何格式属性。

    这是“版式保护模式”的核心：
    - 只改 w:t 的文字，不合并 run、不清空 run、不重建段落；
    - 变量跨多个 run 时，替换值放进变量起点所在的 run，保留该 run 的格式；
    - 变量前后的文字仍留在原来的 run 里，字体、字号、加粗、单元格宽度、
      行高、页边距等全部保持原样。
    """
    texts = [node.text or "" for node in nodes]
    full_text = "".join(texts)
    matches = list(VAR_PATTERN.finditer(full_text))
    if not matches:
        return False

    starts = []
    position = 0
    for text in texts:
        starts.append(position)
        position += len(text)

    changed = False

    def locate(pos: int, is_end: bool):
        for index, start in enumerate(starts):
            end = start + len(texts[index])
            if pos < end:
                return index, pos - start
            if pos == end:
                if is_end or index == len(nodes) - 1:
                    return index, len(texts[index])
                return index + 1, 0
        return len(nodes) - 1, len(texts[-1])

    # 从后往前替换，避免前面的匹配位置被后面的替换长度影响
    for match in reversed(matches):
        raw_name = match.group(1) or match.group(2) or ""
        var_name, _optional = split_optional_marker(raw_name)
        replacement = str(variables.get(var_name, match.group(0)))
        if replacement == match.group(0):
            continue

        start_index, start_offset = locate(match.start(), False)
        end_index, end_offset = locate(match.end(), True)
        start_node = nodes[start_index]
        start_text = texts[start_index]

        if start_index == end_index:
            new_text = start_text[:start_offset] + replacement + start_text[end_offset:]
            start_node.text = new_text
            if new_text != new_text.strip():
                start_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        else:
            prefix = start_text[:start_offset]
            end_text = texts[end_index]
            suffix = end_text[end_offset:]
            start_node.text = prefix + replacement
            if start_node.text != start_node.text.strip():
                start_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            for index in range(start_index + 1, end_index):
                nodes[index].text = ""
            nodes[end_index].text = suffix
            if suffix != suffix.strip():
                nodes[end_index].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        changed = True

    return changed


def _replace_in_docx_part(
    data: bytes,
    variables: Dict[str, Any],
    shrink_overflow_font: bool = True,
) -> Tuple[Optional[bytes], List[str]]:
    """只修改一个 Word XML 部分里的 w:t 文字；没有变化时返回 (None, [])。

    版式保护是默认行为：不合并 run、不动任何格式属性。唯一的例外由
    core.font_fit 控制——当单元格内容因真实数据变长而必然多占行时，
    允许缩小该单元格的字号以保住页数（可在设置里关闭）。
    """
    try:
        from lxml import etree
    except ImportError as error:
        raise RenderError("缺少 lxml 库，无法进行版式保护替换") from error

    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as error:
        raise RenderError(f"Word XML 解析失败：{error}") from error

    # 尽量保留原 XML 前缀，避免无意义的命名空间变化
    for prefix, uri in (root.nsmap or {}).items():
        if prefix:
            try:
                etree.register_namespace(prefix, uri)
            except (ValueError, TypeError):
                pass

    paragraph_tag = f"{{{namespace}}}p"
    text_tag = f"{{{namespace}}}t"
    cell_tag = f"{{{namespace}}}tc"

    # 替换前先快照每个表格单元格的原始文本，供溢出检测对比行数
    original_cell_texts = {}
    cells = list(root.iter(cell_tag))
    for cell in cells:
        original_cell_texts[cell] = _collect_cell_original_texts(cell)

    groups = {}
    for node in root.iter(text_tag):
        paragraph = node
        while paragraph is not None and paragraph.tag != paragraph_tag:
            paragraph = paragraph.getparent()
        if paragraph is not None:
            groups.setdefault(paragraph, []).append(node)

    changed = False
    for nodes in groups.values():
        if _replace_in_paragraph_nodes(nodes, variables):
            changed = True

    adjustments: List[str] = []
    if changed and shrink_overflow_font:
        for cell in cells:
            cell_adjustments = _fit_cell_paragraphs(
                cell, original_cell_texts.get(cell, {}), variables, True
            )
            adjustments.extend(cell_adjustments)

    if not changed and not adjustments:
        return None, []
    return (
        etree.tostring(
            root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        ),
        adjustments,
    )


def _collect_cell_original_texts(cell_element) -> Dict[int, str]:
    try:
        from core.font_fit import collect_cell_original_texts
    except ImportError:
        return {}
    return collect_cell_original_texts(cell_element)


def _fit_cell_paragraphs(cell_element, original_texts, variables, shrink_enabled) -> List[str]:
    try:
        from core.font_fit import fit_cell_paragraphs
    except ImportError:
        return []
    return fit_cell_paragraphs(cell_element, original_texts, variables, shrink_enabled)


def _is_word_text_part(name: str) -> bool:
    """需要替换的 Word XML 部分：正文、页眉页脚、脚注尾注。"""
    if name == "word/document.xml":
        return True
    if re.fullmatch(r"word/(header|footer)\d*\.xml", name):
        return True
    return name in ("word/footnotes.xml", "word/endnotes.xml")


def _render_docx(
    template_path: str,
    output_path: str,
    variables: Dict[str, Any],
    shrink_overflow_font: bool = True,
) -> List[str]:
    """用“版式保护”方式渲染 .docx。

    不加载/保存 python-docx 文档对象，不重建段落或 run；只改 XML 中的
    w:t 文字节点。这样字体、字号、表格列宽/行高、页边距、分页设置、
    页眉页脚和样式定义都保持原样，不会因为替换动作重新排版。

    唯一例外：当单元格内容因真实数据变长而必然多占行时，允许缩小该
    单元格的字号以保住页数（shrink_overflow_font=False 可关闭）。

    :return: 字号调整日志（空列表表示没有动过任何格式）
    """
    try:
        with zipfile.ZipFile(template_path, "r") as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
            comment = archive.comment
    except (zipfile.BadZipFile, OSError) as error:
        raise RenderError(f"模板文件损坏或无法打开：{error}") from error

    changed = False
    adjustments: List[str] = []
    output_entries = []
    for info, data in entries:
        if _is_word_text_part(info.filename):
            new_data, part_adjustments = _replace_in_docx_part(data, variables, shrink_overflow_font)
            if new_data is not None:
                data = new_data
                changed = True
                adjustments.extend(part_adjustments)
        output_entries.append((info, data))

    if not changed:
        shutil.copy2(template_path, output_path)
        return []

    try:
        with zipfile.ZipFile(output_path, "w") as archive:
            archive.comment = comment
            for info, data in output_entries:
                archive.writestr(info, data)
    except OSError as error:
        raise RenderError(f"输出文档写入失败：{error}") from error
    return adjustments


def _render_xlsx(template_path: str, output_path: str, variables: Dict[str, Any]) -> None:
    """渲染 .xlsx 文档"""
    try:
        import openpyxl
    except ImportError:
        raise RenderError("缺少 openpyxl 库，无法处理 .xlsx 文件")

    try:
        wb = openpyxl.load_workbook(template_path)
    except Exception as e:
        raise RenderError(f"模板文件损坏或无法打开：{e}")

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None and isinstance(cell.value, str):
                    if VAR_PATTERN.search(cell.value):
                        cell.value = _replace_in_text(cell.value, variables)

    wb.save(output_path)
    wb.close()


def _render_wps_et(template_path: str, output_path: str, variables: Dict[str, Any]) -> None:
    """
    渲染 .wps/.et 文件（尝试作为 zip/OOXML 处理）。
    新版 WPS 文字 .wps 实质是 docx，WPS 表格 .et 实质是 xlsx。
    """
    ext = os.path.splitext(template_path)[1].lower()
    try:
        with zipfile.ZipFile(template_path, "r") as z:
            names = z.namelist()
            is_docx_like = "word/document.xml" in names
            is_xlsx_like = "xl/workbook.xml" in names
    except zipfile.BadZipFile:
        raise RenderError("旧版 WPS 二进制格式暂不支持变量填充，请另存为 .docx/.xlsx")

    # 复制模板到输出，然后就地修改 zip 内容
    shutil.copy2(template_path, output_path)

    try:
        with zipfile.ZipFile(output_path, "r") as zin:
            file_contents = {name: zin.read(name) for name in zin.namelist()}

        # 对所有 xml 文件做变量替换
        for name in list(file_contents.keys()):
            if name.endswith(".xml") or name.endswith(".rels"):
                try:
                    content = file_contents[name].decode("utf-8")
                    if VAR_PATTERN.search(content):
                        # XML 实体编码处理：变量值可能含特殊字符
                        from xml.sax.saxutils import escape
                        def replacer(m):
                            """XML 中变量替换回调：值做 XML 实体转义"""
                            raw_name = m.group(1) or m.group(2) or ""
                            var_name, _optional = split_optional_marker(raw_name)
                            return escape(str(variables.get(var_name, m.group(0))))
                        content = VAR_PATTERN.sub(replacer, content)
                        file_contents[name] = content.encode("utf-8")
                except (UnicodeDecodeError, Exception):
                    pass

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in file_contents.items():
                zout.writestr(name, data)
    except Exception as e:
        raise RenderError(f"WPS/ET 文件填充失败：{e}")


def render_document(
    template_path: str,
    output_path: str,
    variables: Dict[str, Any],
    shrink_overflow_font: bool = True,
    layout_log: Optional[List[str]] = None,
) -> None:
    """
    渲染单个文档：将模板中的变量替换为变量值，保存到输出路径。
    原始模板文件不会被修改。

    :param shrink_overflow_font: 单元格内容溢出时是否允许缩小字号保住页数
    :param layout_log: 可选列表，收集版式调整记录（如 "第3行：14→11 磅"）
    """
    if not os.path.exists(template_path):
        raise RenderError(f"模板文件不存在：{template_path}")

    ext = os.path.splitext(template_path)[1].lower()

    if ext == ".docx":
        adjustments = _render_docx(template_path, output_path, variables, shrink_overflow_font)
        if layout_log is not None and adjustments:
            name = os.path.basename(template_path)
            layout_log.extend(f"{name} · {msg}" for msg in adjustments)
    elif ext == ".xlsx":
        _render_xlsx(template_path, output_path, variables)
    elif ext in (".wps", ".et"):
        _render_wps_et(template_path, output_path, variables)
    else:
        # 不支持的格式，直接复制
        shutil.copy2(template_path, output_path)

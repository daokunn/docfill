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
from typing import Any, Dict, Optional

from core.scanner import VAR_PATTERN


class RenderError(Exception):
    """文档渲染错误"""
    pass


def _replace_in_text(text: str, variables: Dict[str, Any]) -> str:
    """将文本中的 {{变量名}} 替换为变量值"""
    def replacer(m: re.Match) -> str:
        """正则替换回调：取变量名，从字典取值，找不到则保留原标记"""
        var_name = (m.group(1) or m.group(2) or "").strip()
        return str(variables.get(var_name, m.group(0)))

    return VAR_PATTERN.sub(replacer, text or "")


def _render_docx(template_path: str, output_path: str, variables: Dict[str, Any]) -> None:
    """渲染 .docx 文档"""
    try:
        import docx
    except ImportError:
        raise RenderError("缺少 python-docx 库，无法处理 .docx 文件")

    try:
        doc = docx.Document(template_path)
    except Exception as e:
        raise RenderError(f"模板文件损坏或无法打开：{e}")

    # 处理正文段落
    for para in doc.paragraphs:
        _render_paragraph(para, variables)

    # 处理表格
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _render_paragraph(para, variables)

    # 处理页眉页脚
    for section in doc.sections:
        for para in section.header.paragraphs:
            _render_paragraph(para, variables)
        for para in section.footer.paragraphs:
            _render_paragraph(para, variables)

    doc.save(output_path)


def _render_paragraph(para, variables: Dict[str, Any]) -> None:
    """
    渲染单个段落。
    处理变量标记跨多个 run 的情况：合并所有 run 文本，替换后写回第一个 run，清空其余 run。
    """
    if not para.runs:
        return

    full_text = "".join(run.text for run in para.runs)
    # 快速判断：如果没有变量标记，跳过
    if not VAR_PATTERN.search(full_text):
        return

    new_text = _replace_in_text(full_text, variables)
    # 将新文本写入第一个 run，清空其余 run
    para.runs[0].text = new_text
    for run in para.runs[1:]:
        run.text = ""


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
                            var_name = (m.group(1) or m.group(2) or "").strip()
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


def render_document(template_path: str, output_path: str, variables: Dict[str, Any]) -> None:
    """
    渲染单个文档：将模板中的变量替换为变量值，保存到输出路径。
    原始模板文件不会被修改。
    """
    if not os.path.exists(template_path):
        raise RenderError(f"模板文件不存在：{template_path}")

    ext = os.path.splitext(template_path)[1].lower()

    if ext == ".docx":
        _render_docx(template_path, output_path, variables)
    elif ext == ".xlsx":
        _render_xlsx(template_path, output_path, variables)
    elif ext in (".wps", ".et"):
        _render_wps_et(template_path, output_path, variables)
    else:
        # 不支持的格式，直接复制
        shutil.copy2(template_path, output_path)

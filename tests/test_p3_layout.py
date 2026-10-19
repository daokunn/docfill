"""版式保护回归测试：替换文字，但不改字体/表格/页面设置。"""

import hashlib
import zipfile
from pathlib import Path

from lxml import etree
from docx import Document
from docx.shared import Cm, Pt

from core.renderer import render_document

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _property_hashes(path: Path):
    """收集段落/表格/行/单元格/run 属性的哈希，不包含文字内容。"""
    with zipfile.ZipFile(path) as archive:
        data = archive.read("word/document.xml")
    root = etree.fromstring(data)
    result = {}
    for tag in ("sectPr", "tblPr", "trPr", "tcPr", "pPr", "rPr"):
        values = []
        for node in root.iter(f"{{{W}}}{tag}"):
            values.append(hashlib.sha256(etree.tostring(node)).hexdigest())
        result[tag] = values
    return result


def test_docx_replacement_preserves_formatting(tmp_path):
    template = tmp_path / "format.docx"
    output = tmp_path / "format_out.docx"

    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    table = document.add_table(rows=8, cols=2)
    table.autofit = False
    for index, row in enumerate(table.rows):
        row.height = Pt(28)
        row.cells[0].text = f"字段{index + 1}"
        row.cells[1].text = "内容"

    paragraph = table.cell(0, 1).paragraphs[0]
    paragraph.text = ""
    label = paragraph.add_run("姓名：")
    label.bold = True
    value_run = paragraph.add_run("{{姓名}}")
    value_run.font.size = Pt(14)
    value_run.italic = True

    # 故意把变量拆成 3 个 run，验证跨 run 时也不会清空其他 run 的格式
    split = document.add_paragraph()
    split.add_run("{{")
    split.add_run("手机号")
    split.add_run("}}")
    document.save(template)

    before = _property_hashes(template)
    render_document(str(template), str(output), {"姓名": "张三", "手机号": "13812345678"})

    after = _property_hashes(output)
    assert before == after, "段落/表格/行/单元格/run 属性不应被修改"

    rendered = Document(output)
    text = "\n".join(p.text for p in rendered.paragraphs)
    for table in rendered.tables:
        for row in table.rows:
            text += "\n" + " | ".join(cell.text for cell in row.cells)
    assert "张三" in text
    assert "13812345678" in text
    assert "{{姓名}}" not in text
    assert "{{手机号}}" not in text

    # 替换值仍使用原占位符 run 的格式
    value_cell = rendered.tables[0].cell(0, 1)
    value_run_after = next(run for run in value_cell.paragraphs[0].runs if "张三" in run.text)
    assert value_run_after.italic is True
    assert value_run_after.font.size == Pt(14)

    # 页面设置和行高没有变化（用 int 比较，避免 Cm 浮点转换误差）
    assert rendered.sections[0].top_margin == section.top_margin
    assert rendered.sections[0].left_margin == section.left_margin
    assert rendered.tables[0].rows[0].height == table.rows[0].height


def test_docx_without_variables_is_byte_identical(tmp_path):
    template = tmp_path / "plain.docx"
    output = tmp_path / "plain_out.docx"
    document = Document()
    document.add_paragraph("没有变量的普通文档")
    document.save(template)

    render_document(str(template), str(output), {"姓名": "张三"})
    assert template.read_bytes() == output.read_bytes()

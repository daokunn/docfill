"""回归测试：同一段文字里多个变量必须全部替换。

曾经的问题：反向替换使用旧文本快照，后一个变量替换完会把前一个
变量的结果覆盖回 {{...}}，表现为"表格/Word 里有的变量不替换"。
"""

import os
import tempfile

from docx import Document

from core.renderer import render_document


def test_multiple_variables_in_one_paragraph():
    tmp = tempfile.mkdtemp()
    template = os.path.join(tmp, "t.docx")
    output = os.path.join(tmp, "o.docx")

    doc = Document()
    doc.add_paragraph("姓名：{{姓名}} 分期：{{分期起止年月}} 金额：{{金额}}")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "单位：{{单位}} / {{姓名}}"
    doc.save(template)

    render_document(
        template,
        output,
        {
            "姓名": "张三",
            "分期起止年月": "2024-01至2024-12",
            "金额": "100",
            "单位": "测试单位",
        },
    )

    result = Document(output)
    assert result.paragraphs[0].text == "姓名：张三 分期：2024-01至2024-12 金额：100"
    assert result.tables[0].cell(0, 0).text == "单位：测试单位 / 张三"
    assert "{{" not in result.paragraphs[0].text

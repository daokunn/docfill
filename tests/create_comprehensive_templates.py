"""
生成全面的测试模板文件，覆盖各种边界情况：
- 段落变量、表格变量、页眉页脚变量
- {{}} 和 ${} 两种标记格式
- 带空格的变量标记 {{ 姓名 }}
- 跨 run 的变量（docx）
- 特殊字符变量
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comprehensive_templates")


def create_docx_templates():
    """生成各种 docx 模板"""
    import docx

    # 1. 标准模板：段落 + 表格
    biz_dir = os.path.join(TEST_ROOT, "标准业务")
    os.makedirs(biz_dir, exist_ok=True)

    doc = docx.Document()
    doc.add_heading("标准申请表", level=1)
    doc.add_paragraph("姓名：{{姓名}}")
    doc.add_paragraph("身份证号：{{身份证号}}")
    doc.add_paragraph("手机号：{{手机号}}")
    doc.add_paragraph("申请日期：{{申请日期}}")

    table = doc.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "客户名"
    table.cell(0, 1).text = "{{客户名}}"
    table.cell(1, 0).text = "单位"
    table.cell(1, 1).text = "{{单位}}"
    table.cell(2, 0).text = "地址"
    table.cell(2, 1).text = "{{地址}}"
    table.cell(3, 0).text = "备注"
    table.cell(3, 1).text = "{{备注}}"
    doc.save(os.path.join(biz_dir, "申请表.docx"))

    # 2. 测试 ${} 标记格式
    doc2 = docx.Document()
    doc2.add_paragraph("姓名：${姓名}")
    doc2.add_paragraph("身份证：${身份证号}")
    doc2.add_paragraph("手机：${手机号}")
    doc2.save(os.path.join(biz_dir, "美元符号模板.docx"))

    # 3. 测试带空格的变量标记
    doc3 = docx.Document()
    doc3.add_paragraph("姓名：{{ 姓名 }}")
    doc3.add_paragraph("身份证：{{ 身份证号 }}")
    doc3.save(os.path.join(biz_dir, "带空格模板.docx"))

    # 4. 测试跨 run 的变量（将一个变量标记拆到多个 run）
    doc4 = docx.Document()
    para = doc4.add_paragraph()
    para.add_run("姓名：")
    run1 = para.add_run("{{姓")
    run2 = para.add_run("名}}")
    doc4.save(os.path.join(biz_dir, "跨run模板.docx"))

    # 5. 测试页眉页脚变量
    doc5 = docx.Document()
    section = doc5.sections[0]
    section.header.paragraphs[0].text = "页眉：{{姓名}}"
    section.footer.paragraphs[0].text = "页脚：{{身份证号}}"
    doc5.add_paragraph("正文：{{手机号}}")
    doc5.save(os.path.join(biz_dir, "页眉页脚模板.docx"))

    # 6. 测试多日期字段
    doc6 = docx.Document()
    doc6.add_paragraph("开始日期：{{开始日期}}")
    doc6.add_paragraph("结束日期：{{结束日期}}")
    doc6.add_paragraph("申请日期：{{申请日期}}")
    doc6.add_paragraph("出生日期：{{出生日期}}")
    doc6.save(os.path.join(biz_dir, "多日期模板.docx"))

    print(f"创建 docx 模板到：{biz_dir}")


def create_xlsx_templates():
    """生成各种 xlsx 模板"""
    import openpyxl

    biz_dir = os.path.join(TEST_ROOT, "标准业务")

    # 1. 标准 xlsx
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "信息登记"
    ws["A1"] = "姓名"
    ws["B1"] = "{{姓名}}"
    ws["A2"] = "身份证号"
    ws["B2"] = "{{身份证号}}"
    ws["A3"] = "手机号"
    ws["B3"] = "{{手机号}}"
    ws["A4"] = "单位"
    ws["B4"] = "{{单位}}"
    ws["A5"] = "申请日期"
    ws["B5"] = "{{申请日期}}"
    ws["A6"] = "备注"
    ws["B6"] = "{{备注}}"
    # 测试 ${} 格式
    ws["A7"] = "客户名"
    ws["B7"] = "${客户名}"
    wb.save(os.path.join(biz_dir, "信息登记表.xlsx"))

    # 2. 跨单元格变量（变量名在合并单元格中）
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2["A1"] = "{{姓名}}"
    ws2.merge_cells("A1:B1")
    ws2["A2"] = "{{身份证号}}"
    ws2.merge_cells("A2:B2")
    wb2.save(os.path.join(biz_dir, "合并单元格模板.xlsx"))

    # 3. 多 sheet 模板
    wb3 = openpyxl.Workbook()
    ws3 = wb3.active
    ws3.title = "基本信息"
    ws3["A1"] = "{{姓名}}"
    ws3["A2"] = "{{身份证号}}"
    ws4 = wb3.create_sheet("联系方式")
    ws4["A1"] = "{{手机号}}"
    ws4["A2"] = "{{单位}}"
    wb3.save(os.path.join(biz_dir, "多sheet模板.xlsx"))

    print(f"创建 xlsx 模板到：{biz_dir}")


def create_special_char_templates():
    """生成包含特殊字符的模板"""
    import docx
    import openpyxl

    biz_dir = os.path.join(TEST_ROOT, "特殊字符业务")
    os.makedirs(biz_dir, exist_ok=True)

    # docx 特殊字符
    doc = docx.Document()
    doc.add_paragraph("姓名：{{姓名}}")
    doc.add_paragraph("单位：{{单位}}")
    doc.add_paragraph("地址：{{地址}}")
    doc.add_paragraph("备注：{{备注}}")
    doc.save(os.path.join(biz_dir, "特殊字符.docx"))

    # xlsx 特殊字符
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "{{姓名}}"
    ws["A2"] = "{{单位}}"
    ws["A3"] = "{{地址}}"
    ws["A4"] = "{{备注}}"
    wb.save(os.path.join(biz_dir, "特殊字符.xlsx"))

    print(f"创建特殊字符模板到：{biz_dir}")


def create_empty_var_templates():
    """生成包含空值场景的模板"""
    import docx

    biz_dir = os.path.join(TEST_ROOT, "空值业务")
    os.makedirs(biz_dir, exist_ok=True)

    doc = docx.Document()
    doc.add_paragraph("姓名：{{姓名}}")
    doc.add_paragraph("身份证号：{{身份证号}}")
    doc.add_paragraph("可选字段：{{备注}}")  # 可选变量
    doc.save(os.path.join(biz_dir, "空值测试.docx"))

    print(f"创建空值模板到：{biz_dir}")


def main():
    create_docx_templates()
    create_xlsx_templates()
    create_special_char_templates()
    create_empty_var_templates()
    print(f"\n全部测试模板已生成到：{TEST_ROOT}")


if __name__ == "__main__":
    main()

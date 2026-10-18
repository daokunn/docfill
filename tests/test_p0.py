"""P0 回归测试：日期格式、字段映射、多人、客户名兜底、模板备份。"""

from pathlib import Path

from core.date_format import format_output_values, parse_date_value
from core.field_mapper import map_fields_to_template
from core.parser import SmartParser
from core.scanner import count_variable_occurrences, scan_businesses
from core.template_backup import backup_templates, get_last_backup, restore_backup
from output.file_output import OutputManager

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "examples" / "templates"


def test_parse_date_value_validation():
    assert parse_date_value("20260101").isoformat() == "2026-01-01"
    assert parse_date_value("2026年1月1日").isoformat() == "2026-01-01"
    assert parse_date_value("20260001") is None  # 非法月份，不能当日期
    assert parse_date_value("2026-02-30") is None


def test_date_output_format():
    values = {
        "开始时间": "2026-01-01",
        "结束时间": "2026-03-30",
        "起止日期": "2026-01-01~2026-03-30",
        "项目编号": "20260001",
        "备注": "20260101",
    }
    result = format_output_values(values, "YYYY年M月D日", "至")

    assert result["开始时间"] == "2026年1月1日"
    assert result["结束时间"] == "2026年3月30日"
    assert result["起止日期"] == "2026年1月1日至2026年3月30日"
    assert result["项目编号"] == "20260001"
    # 备注不是日期字段，保持原样
    assert result["备注"] == "20260101"


def test_date_range_and_aliases():
    parser = SmartParser()
    result = parser.parse("开始时间：20260101\n结束时间：20260330")
    values = {field.field: field.value for field in result.fields}

    assert values["开始日期"] == "2026-01-01"
    assert values["结束日期"] == "2026-03-30"

    mapped = map_fields_to_template(result.fields, ["开始时间", "结束时间"])
    assert [field.field for field in mapped] == ["开始时间", "结束时间"]
    assert mapped[0].mapped_from == "开始日期"


def test_range_field_mapping_drops_unused_range():
    parser = SmartParser()
    result = parser.parse("20260101-20260330")
    mapped = map_fields_to_template(result.fields, ["开始时间", "结束时间"])

    assert [field.field for field in mapped] == ["开始时间", "结束时间"]
    assert all(field.field != "起止日期" for field in mapped)


def test_project_code_not_converted_to_date():
    parser = SmartParser()
    result = parser.parse("项目编号：20260001")
    values = {field.field: field.value for field in result.fields}
    assert values["项目编号"] == "20260001"


def test_address_alias_maps_to_address():
    parser = SmartParser()
    result = parser.parse("姓名：张三\n家庭住址：江西省赣州市章贡区红旗大道123号")
    fields = {field.field: field.value for field in result.fields}

    assert fields["地址"] == "红旗大道123号"
    assert fields["省"] == "江西省"
    assert fields["市"] == "赣州市"
    assert fields["区"] == "章贡区"


def test_multi_person_blank_line_separator():
    parser = SmartParser()
    text = (
        "姓名：张三\n身份证号：360700199001011234\n"
        "\n"
        "姓名：李四\n身份证号：360700199203035678"
    )
    assert len(parser.split_multi(text)) == 2


def test_customer_name_fallback():
    manager = OutputManager()
    folder = manager.build_subfolder_name("公务卡申请", {"姓名": "张三"})
    assert "张三" in folder
    assert "未知客户" not in folder


def test_template_backup_and_restore(tmp_path):
    template = tmp_path / "模板.docx"
    template.write_bytes(b"original")

    record = backup_templates([str(template)], backup_root=str(tmp_path / "backups"))
    template.write_bytes(b"modified")

    assert get_last_backup(str(tmp_path / "backups"))
    assert restore_backup(record, str(tmp_path / "backups")) == 1
    assert template.read_bytes() == b"original"


def test_count_variable_occurrences():
    template = TEMPLATES / "公务卡申请" / "申请表.docx"
    count = count_variable_occurrences(str(template), {"姓名": "客户名"})
    assert count >= 1


def test_scan_examples_has_customer_name_variable():
    businesses = scan_businesses(str(TEMPLATES))
    application = next(b for b in businesses if b.name == "公务卡申请")
    assert "姓名" in application.variables

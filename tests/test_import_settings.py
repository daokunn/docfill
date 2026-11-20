# -*- coding: utf-8 -*-
"""导入占位行、新设置默认值、名单损坏保护。"""
import json
import os

from config.settings import DEFAULT_SETTINGS
from core.roster import roster_path
from core.roster_batches import active_roster, batch_index_path
from core.table_import import is_template_placeholder_row, read_table_file
from output.roster_export import write_template_xlsx


def test_new_setting_defaults():
    assert DEFAULT_SETTINGS["batch_import_mode"] == "new_batch"
    assert DEFAULT_SETTINGS["number_manual_mode"] == "once"
    assert DEFAULT_SETTINGS["date_format_overrides"] == {}
    shortcuts = DEFAULT_SETTINGS["shortcuts"]
    for key in ("next_case", "open_output", "import", "generate_selected",
                "delete_rows", "export", "bulk_set"):
        assert key in shortcuts


def test_placeholder_rows_detected():
    header = ["姓名", "身份证号", "地址"]
    assert is_template_placeholder_row(header, ["张三", "360700199001011234", ""])
    assert is_template_placeholder_row(
        header, ["说明：第一行是变量标题，从第二行开始每行一个人。", "", ""])
    assert not is_template_placeholder_row(
        header, ["张三", "36070019900101123X", "赣州市"])
    assert not is_template_placeholder_row(header, ["李四", "", ""])


def test_read_table_file_skips_template_placeholders(tmp_path):
    path = str(tmp_path / "template.xlsx")
    write_template_xlsx(path, ["姓名", "身份证号", "地址"], key_field="姓名")
    header, rows, _kind, warnings = read_table_file(path)
    assert header == ["姓名", "身份证号", "地址"]
    assert rows == []
    assert warnings == []


def test_corrupt_legacy_roster_is_backed_up_and_reported(tmp_path):
    root = str(tmp_path)
    legacy = roster_path("测试业务", storage_dir=root)
    with open(legacy, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    roster = active_roster("测试业务", storage_dir=root)
    assert roster.load_error and ("损坏" in roster.load_error or "读取失败" in roster.load_error)
    backups = [n for n in os.listdir(root) if "roster_测试业务.json.corrupt" in n]
    assert len(backups) == 1
    with open(batch_index_path("测试业务", storage_dir=root), encoding="utf-8") as f:
        index = json.load(f)
    assert index.get("migration_error")

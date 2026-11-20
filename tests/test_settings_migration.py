# -*- coding: utf-8 -*-
"""老配置一次性安全迁移：改过默认值后，已存在的 settings.json 也要跟上。"""
from config.settings import migrate_legacy_settings


def test_delete_shortcut_migrated_from_del():
    data = {"shortcuts": {"delete_rows": "Del", "generate": "Ctrl+G"}}
    out = migrate_legacy_settings(data)
    assert out["shortcuts"]["delete_rows"] == "Ctrl+Delete"
    assert out["shortcuts"]["generate"] == "Ctrl+G"   # 其它快捷键不动


def test_migration_only_once():
    data = {"shortcuts": {"delete_rows": "Ctrl+Delete"},
            "_safety_migrated": True}
    out = migrate_legacy_settings(data)
    assert out["shortcuts"]["delete_rows"] == "Ctrl+Delete"
    assert out["_safety_migrated"] is True


def test_silent_print_migrated_to_false():
    data = {"silent_print": True}
    out = migrate_legacy_settings(data)
    assert out["silent_print"] is False
    assert out["_safety_migrated"] is True


def test_user_custom_shortcut_kept():
    data = {"shortcuts": {"delete_rows": "Ctrl+Backspace"}}
    out = migrate_legacy_settings(data)
    assert out["shortcuts"]["delete_rows"] == "Ctrl+Backspace"

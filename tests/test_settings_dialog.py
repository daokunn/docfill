# -*- coding: utf-8 -*-
"""设置窗口回归测试：分页重构后点【设置】不能再因缺失属性崩溃。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class StubSettings:
    """只提供设置窗口需要的 get/set，避免测试污染真实 settings.json。"""

    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def test_settings_dialog_builds_without_attribute_error(qapp):
    """原 bug：_build_ui -> _refresh_open_print_summary 访问不存在的 open_print_config。"""
    from ui.main_window import SettingsDialog

    dlg = SettingsDialog(
        StubSettings(), variable_names=["姓名", "身份证号"],
        business_name="测试业务", template_names=["模板A.docx"],
    )
    try:
        assert hasattr(dlg, "open_print_config")
        assert dlg.open_print_config["open_files_mode"] == "all"
        # 摘要标签应已被 _refresh_open_print_summary 填充
        assert dlg.open_print_summary.text()
    finally:
        dlg.close()


def test_settings_dialog_reads_saved_open_print_config(qapp):
    """已保存的打开/打印设置必须被带进窗口并正确显示摘要。"""
    from ui.main_window import SettingsDialog

    settings = StubSettings({
        "open_generated_files": True,
        "open_files_mode": "specified",
        "open_files_templates": ["模板A.docx"],
        "auto_print_after_open": True,
        "print_copies": 2,
        "silent_print": True,
    })
    dlg = SettingsDialog(
        settings, variable_names=["姓名"], business_name="测试业务",
        template_names=["模板A.docx"],
    )
    try:
        assert dlg.open_print_config["open_files_mode"] == "specified"
        text = dlg.open_print_summary.text()
        assert "指定模板" in text
        assert "自动打印" in text
        assert "2 份" in text
    finally:
        dlg.close()


def test_settings_dialog_accept_saves_all_keys(qapp):
    """点确定不能崩，且把打开/打印配置写回设置。"""
    from ui.main_window import SettingsDialog

    settings = StubSettings()
    dlg = SettingsDialog(
        settings, variable_names=["姓名", "身份证号"],
        business_name="测试业务", template_names=["模板A.docx"],
    )
    dlg._on_accept()
    assert settings.data["open_files_mode"] in ("all", "first", "specified")
    assert "print_copies" in settings.data
    assert "shortcuts" in settings.data


def test_settings_ui_section_headers_and_all_shortcut_inputs(qapp):
    """UI 优化回归：分节头带样式名；快捷键改两列后所有输入框仍在。"""
    from PySide6.QtWidgets import QLabel
    from ui.main_window import SettingsDialog, SettingsDialog as SD

    dlg = SettingsDialog(
        StubSettings(), variable_names=["姓名"],
        business_name="测试业务", template_names=[],
    )
    try:
        sections = [w for w in dlg.findChildren(QLabel)
                    if w.objectName() == "formSection"]
        assert len(sections) >= 5, "设置页分节头丢失"
        # 主窗口 6 个 + 批量 5 个快捷键输入框，一个都不能少
        expected = set(SD.MAIN_SHORTCUTS) | set(SD.BATCH_SHORTCUTS)
        assert set(dlg._shortcut_inputs.keys()) == expected
        # 分节头样式必须在全局 QSS 中有定义
        from ui.style import APP_STYLE
        assert "QLabel#formSection" in APP_STYLE
    finally:
        dlg.close()

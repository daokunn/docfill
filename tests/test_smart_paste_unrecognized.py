# -*- coding: utf-8 -*-
"""智能粘贴待确认区回归测试：
1) 多人模式下未识别片段不再被丢弃（切人时正确显示）
2) 待确认区赋值下拉只列空变量，不再用"大部分已填充"的下拉迷惑用户
3) 提供"忽略全部"按钮，明确告诉用户这些片段可以不管
4) 待确认区说明用大白话，不再只有"未识别片段/赋值"术语
"""
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


def _make_dialog(variable_dict):
    from ui.smart_paste_dialog import SmartPasteDialog
    return SmartPasteDialog(variable_dict=variable_dict)


def test_multi_unrecognized_preserved_when_switch_person(qapp):
    """多人模式：切换到某人时，待确认区要显示该人的未识别片段。"""
    dlg = _make_dialog({"姓名": "", "身份证号": ""})
    dlg.multi_fields = [[], []]
    dlg.multi_unrecognized = [["紧急联系人李四"], ["备注 blah"]]
    dlg.multi_selector.addItem("第1人")
    dlg.multi_selector.addItem("第2人")

    dlg._on_switch_person(0)
    assert dlg.unrec_list.count() == 1
    assert dlg.unrec_list.item(0).text() == "紧急联系人李四"

    dlg._on_switch_person(1)
    assert dlg.unrec_list.count() == 1
    assert dlg.unrec_list.item(0).text() == "备注 blah"


def test_unrec_dropdown_only_lists_empty_vars(qapp):
    """待确认区赋值下拉：只列空变量，不列已有值的变量。"""
    dlg = _make_dialog({"姓名": "", "单位": "某某公司", "电话": "13800000000"})
    items = dlg._get_unrec_var_items()
    assert any("姓名" in i for i in items)
    assert not any("单位" in i for i in items)
    assert not any("电话" in i for i in items)


def test_ignore_button_clears_unrecognized(qapp):
    """忽略全部：一键清空待确认区，且不写入任何字段。"""
    dlg = _make_dialog({"姓名": ""})
    before = len(dlg.fields)
    dlg.unrec_list.addItem("这是废话片段")
    dlg.unrec_list.addItem("这也是废话")
    dlg._on_ignore_unrec()
    assert dlg.unrec_list.count() == 0
    assert len(dlg.fields) == before


def test_unrec_hint_plain_language(qapp):
    """说明文字要用大白话，明确'可以不管也能生成'。"""
    dlg = _make_dialog({"姓名": ""})
    text = dlg.lbl_unrec_hint.text()
    assert ("不管" in text or "忽略" in text or "不用" in text), text
    assert ("生成" in text or "影响" in text or "跳过" in text), text

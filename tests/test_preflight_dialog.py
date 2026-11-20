"""生成前检查确认框：就地展示 + 展开明细（离屏 UI 测试，不多开窗口）。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from core.preflight import INLINE_DETAIL_THRESHOLD
from ui.preflight_dialog import PreflightDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_few_variables_all_inline_no_button(app):
    dialog = PreflightDialog(
        missing=["姓名", "手机号"],
        summary_lines=["输出目录：测试"],
    )
    assert dialog.missing["needs_detail_button"] is False
    assert getattr(dialog, "detail_label", None) is None
    assert not hasattr(dialog, "btn_detail")


def test_many_variables_expand_in_same_dialog(app):
    names = [f"字段{i}" for i in range(INLINE_DETAIL_THRESHOLD + 4)]
    dialog = PreflightDialog(missing=names)
    assert dialog.missing["needs_detail_button"] is True
    assert dialog.detail_label is not None
    dialog.show()
    assert dialog.detail_label.isHidden(), "明细默认收起"
    assert dialog.btn_detail.isVisible()

    # 点开：同一窗口内展开，不新建子窗口
    dialog.btn_detail.setChecked(True)
    assert dialog.detail_label.isVisible()
    assert "收起" in dialog.btn_detail.text()
    dialog.btn_detail.setChecked(False)
    assert dialog.detail_label.isHidden()
    dialog.close()


def test_confirm_and_cancel_decision(app):
    dialog = PreflightDialog(missing=["姓名"])
    dialog._on_confirm()
    assert dialog.confirmed is True

    dialog2 = PreflightDialog(missing=["姓名"])
    dialog2.reject()
    assert dialog2.confirmed is False


def test_dialog_uses_current_theme_stylesheet(app):
    dialog = PreflightDialog(missing=["姓名"])
    sheet = dialog.styleSheet()
    assert "QPushButton#generate" in sheet  # 来自主题 QSS

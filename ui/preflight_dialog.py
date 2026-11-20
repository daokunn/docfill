"""生成前检查确认框：缺失变量就地展示，多的用"详细查看"就地展开。

用户诉求：变量没输入时让用户决定是否仍然生成；变量少就直接列在框里，
变量多就给个"详细查看"按钮就地展开，不再多弹一个窗口。

本模块只负责展示与收集"仍然生成 / 返回修改"的决定，不改变任何生成行为。
"""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)

from core.preflight import format_missing_section

from ui.style import current_style, palette, current_theme


class PreflightDialog(QDialog):
    """生成前检查确认框。

    :param title: 窗口标题（单人/批量不同）
    :param headline: 一句话概述，例如"即将生成文档，请确认以下信息。"
    :param summary_lines: 顶部固定信息行（输出目录、模板数等）
    :param missing: 缺失变量名列表——少则全列，多则折叠到"详细查看"
    :param extra_warnings: 其它警示行（未知客户、校验问题等），始终展开
    :param confirm_text: 确认按钮文字
    """

    def __init__(self, parent=None, *, title: str = "生成前检查",
                 headline: str = "即将生成文档，请确认以下信息。",
                 summary_lines: Optional[List[str]] = None,
                 missing: Optional[List[str]] = None,
                 missing_label: str = "以下模板变量为空（未填位置会留空）：",
                 extra_warnings: Optional[List[str]] = None,
                 confirm_text: str = "仍然生成",
                 cancel_text: str = "返回修改"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(current_style())
        self.setMinimumWidth(520)
        self.setMaximumWidth(760)
        self._confirmed = False
        p = palette(current_theme())
        self._fg = p["text"]
        self._muted = p["text_muted"]
        self._warn_fg = p["warn"]
        self._bad_bg = p["bad_bg"]

        self.summary_lines = list(summary_lines or [])
        self.extra_warnings = list(extra_warnings or [])
        self.missing = format_missing_section(list(missing or []))
        self.missing_label = missing_label

        self._build_ui(headline, confirm_text, cancel_text)

    def _build_ui(self, headline: str, confirm_text: str, cancel_text: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        head = QLabel(f"<b style='font-size:12pt;'>{headline}</b>")
        head.setWordWrap(True)
        outer.addWidget(head)

        if self.summary_lines:
            summary = QLabel("\n".join(self.summary_lines))
            summary.setWordWrap(True)
            summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
            summary.setStyleSheet(f"color:{self._muted};")
            outer.addWidget(summary)

        # 缺失变量分区：少则就地全列，多则折叠 + 同窗"详细查看"
        if self.missing["total"]:
            card = QFrame()
            card.setStyleSheet(
                f"QFrame{{background:{self._bad_bg}; border:1px solid {self._warn_fg};"
                f" border-radius:8px;}}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            title = QLabel(f"<b style='color:{self._warn_fg};'>{self.missing_label}</b>")
            title.setWordWrap(True)
            card_layout.addWidget(title)

            # 直接显示的部分
            visible = QLabel("、".join(self.missing["visible"]))
            visible.setWordWrap(True)
            visible.setTextInteractionFlags(Qt.TextSelectableByMouse)
            visible.setStyleSheet(f"color:{self._fg};")
            card_layout.addWidget(visible)

            # 折叠的其余部分：默认隐藏，点"详细查看"就地展开
            self.detail_label = None
            if self.missing["needs_detail_button"] and self.missing["hidden"]:
                self.detail_label = QLabel("、".join(self.missing["hidden"]))
                self.detail_label.setWordWrap(True)
                self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                self.detail_label.setStyleSheet(f"color:{self._fg};")
                self.detail_label.hide()
                card_layout.addWidget(self.detail_label)

                self.btn_detail = QPushButton(f"详细查看（另有 {len(self.missing['hidden'])} 项）")
                self.btn_detail.setObjectName("ghost")
                self.btn_detail.setCheckable(True)
                self.btn_detail.setCursor(Qt.PointingHandCursor)
                self.btn_detail.toggled.connect(self._on_toggle_detail)
                card_layout.addWidget(self.btn_detail)

            count = QLabel(f"共 {self.missing['total']} 项未填；空着的地方会留空写入文档。")
            count.setWordWrap(True)
            count.setStyleSheet(f"color:{self._muted}; font-size:9pt;")
            card_layout.addWidget(count)
            outer.addWidget(card)

        # 其它警示（未知客户 / 校验问题）
        if self.extra_warnings:
            warn = QLabel("\n".join(self.extra_warnings))
            warn.setWordWrap(True)
            warn.setTextInteractionFlags(Qt.TextSelectableByMouse)
            warn.setStyleSheet(f"color:{self._warn_fg};")
            outer.addWidget(warn)

        outer.addStretch(1)

        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton(cancel_text)
        btn_cancel.setMinimumWidth(96)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        btn_confirm = QPushButton(confirm_text)
        btn_confirm.setObjectName("primary")
        btn_confirm.setMinimumWidth(96)
        btn_confirm.clicked.connect(self._on_confirm)
        row.addWidget(btn_confirm)
        outer.addLayout(row)

    def _on_toggle_detail(self, checked: bool) -> None:
        """就地展开/收起明细，不新开窗口。"""
        if self.detail_label is not None:
            self.detail_label.setVisible(checked)
        self.btn_detail.setText(
            "收起明细" if checked
            else f"详细查看（另有 {len(self.missing['hidden'])} 项）")

    def _on_confirm(self) -> None:
        self._confirmed = True
        self.accept()

    @property
    def confirmed(self) -> bool:
        return self._confirmed and self.result() == QDialog.Accepted

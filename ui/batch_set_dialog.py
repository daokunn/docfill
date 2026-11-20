"""批量设值对话框：给一批人统一设置某个字段。"""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QRadioButton, QVBoxLayout, QMessageBox,
)

from ui.style import current_style


class BatchSetDialog(QDialog):
    """字段 + 值 + 作用范围，一次给多行设置同一个值。

    安全默认（对齐用户反馈）：
      - 没选行时不再默认"全部行"，而是默认可见行；范围始终可见、可改；
      - 值留空会清空字段，必须二次确认；
      - 界面实时预估"将修改 N 行的 [字段] 为 [值]"，点确定前就能看清后果。
    """

    def __init__(self, columns: List[str], selected_count: int,
                 visible_count: int, total_count: int,
                 preferred_column: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(current_style())
        self.setWindowTitle("批量设值")
        self.setMinimumWidth(480)
        self.result_data: Optional[Dict[str, object]] = None
        self._selected_count = selected_count
        self._visible_count = visible_count
        self._total_count = total_count

        layout = QVBoxLayout(self)
        hint = QLabel(
            "只改选定的范围。已生成的行默认跳过，避免改到已经出过文档的人。\n"
            "留空值会【清空】该字段，请务必看清下方预估再确定。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6b7280;")
        layout.addWidget(hint)

        form = QFormLayout()
        self.column_combo = QComboBox()
        for name in columns:
            self.column_combo.addItem(name, name)
        if preferred_column:
            index = self.column_combo.findData(preferred_column)
            if index >= 0:
                self.column_combo.setCurrentIndex(index)
        self.column_combo.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("字段：", self.column_combo)

        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("统一填写的值；要清空请留空并确认")
        self.value_edit.textChanged.connect(self._refresh_preview)
        form.addRow("统一值：", self.value_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("<b>作用范围</b>"))
        self.radio_selected = QRadioButton(f"选中的行（{selected_count} 行）")
        self.radio_visible = QRadioButton(f"当前筛选可见的行（{visible_count} 行）")
        self.radio_all = QRadioButton(f"全部行（{total_count} 行）")
        # 安全默认：优先选中行；没选行时默认可见行；都没有才全部行（含二次确认）
        if selected_count > 0:
            self.radio_selected.setChecked(True)
        elif visible_count > 0:
            self.radio_visible.setChecked(True)
        else:
            self.radio_all.setChecked(True)
        for radio in (self.radio_selected, self.radio_visible, self.radio_all):
            radio.toggled.connect(self._refresh_preview)
            layout.addWidget(radio)

        self.skip_generated = QCheckBox("跳过已生成的行（推荐）")
        self.skip_generated.setChecked(True)
        self.skip_generated.toggled.connect(self._refresh_preview)
        layout.addWidget(self.skip_generated)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(
            "color:#0f766e; background:#eef7f4; border-radius:6px; padding:8px;")
        layout.addWidget(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_preview()

    def _target_count(self) -> int:
        if self.radio_selected.isChecked():
            return self._selected_count
        if self.radio_visible.isChecked():
            return self._visible_count
        return self._total_count

    def scope(self) -> str:
        if self.radio_visible.isChecked():
            return "visible"
        if self.radio_all.isChecked():
            return "all"
        if self.radio_selected.isChecked():
            return "selected"
        return "all"

    def _refresh_preview(self) -> None:
        column = self.column_combo.currentData() or "（未选字段）"
        value = self.value_edit.text().strip()
        count = self._target_count()
        skip = "（跳过已生成行，实际可能更少）" if self.skip_generated.isChecked() else ""
        action = f"设为「{value}」" if value else "【清空】"
        self.preview_label.setText(
            f"将修改 {count} 行的 [{column}]，{action}{skip}。")

    def _on_accept(self) -> None:
        column = self.column_combo.currentData()
        if not column:
            return
        value = self.value_edit.text().strip()
        count = self._target_count()

        # 留空 = 清空，必须二次确认（防误操作）
        if not value:
            reply = QMessageBox.warning(
                self, "确认清空",
                f"你留空了统一值，将【清空】{count} 行的 [{column}]。\n"
                "这个操作不可撤销，确定继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self.result_data = {
            "column": str(column),
            "value": value,
            "scope": self.scope(),
            "skip_generated": self.skip_generated.isChecked(),
        }
        self.accept()

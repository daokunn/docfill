"""快速修改下一个自动编号。

主界面左下角显示“下个编号”时，旁边有一个【改编号…】按钮：
不用进设置，直接改“下一次要用的号码”。
"""

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.autonumber import AutoNumberBook


class NumberFixDialog(QDialog):
    """直接指定下一次生成的编号（不要求等于 last+1）。"""

    def __init__(self, fields: List[str], book: AutoNumberBook, parent=None):
        super().__init__(parent)
        self.fields = [str(f) for f in fields if str(f).strip()]
        self.book = book
        self.setWindowTitle("修改下一个编号")
        self.setMinimumSize(760, 360)
        self.resize(960, 440)
        self.setSizeGripEnabled(True)
        self._build_ui()
        self._fill()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel(
            "直接改“下一个要用的编号”。生成文档时就用这个号，之后自动按它的下一个继续。\n"
            "例如现在显示 003，但你发现 002 才是对的：把下一号改成 002 即可。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#374151;")
        layout.addWidget(tip)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["变量名", "当前已用到", "下一个要用的编号（可改）"])
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setStretchLastSection(True)
        header.resizeSection(0, 190)
        header.resizeSection(1, 260)
        self.table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_restore = QPushButton("恢复自动递增")
        btn_restore.setToolTip("清除手动指定的下一号，改回按当前已用号自动 +1")
        btn_restore.clicked.connect(self._on_restore)
        row.addWidget(btn_restore)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill(self) -> None:
        self.table.setRowCount(0)
        for field in self.fields:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(field)
            name_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, name_item)
            last = str((self.book.data.get(field) or {}).get("last") or "")
            last_item = QTableWidgetItem(last)
            last_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 1, last_item)
            next_item = QTableWidgetItem(self.book.peek(field))
            next_item.setToolTip("想用哪个号就填哪个号；保存后下一次生成直接用它")
            self.table.setItem(row, 2, next_item)
        if self.fields:
            self.table.selectRow(0)

    def _on_restore(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.fields):
            QMessageBox.information(self, "提示", "请先选择一行")
            return
        field = self.fields[row]
        self.book.set_next(field, "")
        self.table.item(row, 2).setText(self.book.peek(field))

    def _on_accept(self) -> None:
        changes: Dict[str, str] = {}
        for row, field in enumerate(self.fields):
            item = self.table.item(row, 2)
            value = item.text().strip() if item else ""
            if not value:
                QMessageBox.warning(
                    self, "编号不能为空", f"「{field}」的下一个编号不能为空。")
                return
            changes[field] = value
        for field, value in changes.items():
            self.book.set_next(field, value)
        self.accept()

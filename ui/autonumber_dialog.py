"""自动编号配置对话框（独立大窗口）。

设置界面里只放一个入口按钮，真正编辑放到这里：表格铺满窗口，
每个变量一行，勾选 + 填起始号 + 实时预览下一个号码，不会挤在小格子里。
"""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from core.autonumber import AutoNumberBook, increment


class AutoNumberDialog(QDialog):
    """选择需要自动编号的变量并填写起始号。"""

    def __init__(self, variable_names: List[str], configured: Dict[str, str],
                 business_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动编号设置")
        self.resize(820, 620)
        self.variable_names = [str(v) for v in (variable_names or []) if str(v).strip()]
        self.configured = dict(configured or {})
        self.fields: Dict[str, str] = {}

        self.book = AutoNumberBook(business_name) if business_name else None

        self._build_ui()
        self._refresh_all_previews()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel(
            "勾选需要自动生成的变量（可多选），填好起始号。\n"
            "只有真正生成文档时才 +1：没有文档不会占号，因此不会断号。\n"
            "格式随意，程序只把最后一段数字加 1（如 XJH202242312300001 → …002）。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#374151;")
        layout.addWidget(tip)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["启用", "变量名", "起始编号"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().resizeSection(0, 64)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().resizeSection(2, 300)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("下个号码预览："))
        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet("color:#2563eb; font-weight:bold;")
        self.preview_label.setWordWrap(True)
        preview_row.addWidget(self.preview_label, 1)
        layout.addLayout(preview_row)

        self._fill_rows()

        action_row = QHBoxLayout()
        btn_rollback = QPushButton("回收最后一个号")
        btn_rollback.setToolTip("生成错了/删了文件时用：把已发放的最后一个号退回，避免断号")
        btn_rollback.clicked.connect(self._on_rollback_one)
        btn_set = QPushButton("手动设定当前号…")
        btn_set.setToolTip("直接指定已发放到哪一号，下一次从它的下一个开始")
        btn_set.clicked.connect(self._on_set_last)
        action_row.addWidget(btn_rollback)
        action_row.addWidget(btn_set)
        action_row.addStretch()
        layout.addLayout(action_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _fill_rows(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, name in enumerate(self.variable_names):
            self.table.insertRow(row)
            check = QTableWidgetItem("")
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if name in self.configured else Qt.Unchecked)
            self.table.setItem(row, 0, check)

            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 1, name_item)

            seed_item = QTableWidgetItem(str(self.configured.get(name, "") or ""))
            seed_item.setToolTip("第一个要用的编号，例如 XJH202242312300001")
            self.table.setItem(row, 2, seed_item)
        self.table.blockSignals(False)

    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        self._refresh_all_previews()

    def _candidate(self, row: int) -> str:
        """按“已发放的最后一个号”计算下一个；没有则用起始号。"""
        name_item = self.table.item(row, 1)
        seed_item = self.table.item(row, 2)
        name = name_item.text() if name_item else ""
        seed = seed_item.text().strip() if seed_item else ""
        last = ""
        stored_seed = ""
        if self.book is not None:
            record = self.book.data.get(name) or {}
            last = str(record.get("last") or "")
            stored_seed = str(record.get("seed") or "")
        # 用户把起始号改掉了，视为重新起号，预览直接显示新起始号
        if seed != stored_seed:
            return seed
        if last:
            return increment(last)
        return seed

    def _refresh_all_previews(self) -> None:
        parts = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            if not check or not name_item:
                continue
            if check.checkState() != Qt.Checked:
                continue
            nxt = self._candidate(row)
            if nxt:
                parts.append(f"{name_item.text()} → {nxt}")
        self.preview_label.setText("；".join(parts) if parts else "（未勾选任何变量）")

    def _checked_fields(self) -> List[str]:
        fields: List[str] = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            if check and check.checkState() == Qt.Checked and name_item:
                fields.append(name_item.text())
        return fields

    def _on_rollback_one(self) -> None:
        """把勾选变量已发放的最后一个号退回。"""
        fields = self._checked_fields()
        if not fields:
            QMessageBox.information(self, "提示", "请先勾选要回收号码的变量")
            return
        if self.book is None:
            return
        ret = QMessageBox.question(
            self, "回收最后一个号",
            "将把以下变量的最后一个已发放号码退回：\n" + "、".join(fields)
            + "\n\n适用于生成错了、或删掉了刚生成的文件。是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        for name in fields:
            self.book.rollback_one(name)
        self._refresh_all_previews()

    def _on_set_last(self) -> None:
        """手动指定某个变量已发放到哪一号。"""
        fields = self._checked_fields()
        if not fields:
            QMessageBox.information(self, "提示", "请先勾选要设定的变量")
            return
        if self.book is None:
            return
        name = fields[0]
        if len(fields) > 1:
            title = "手动设定当前号（只处理第一个勾选变量）"
            message = f"将只设置「{name}」，其余勾选变量不受影响。当前号设为："
        else:
            title = "手动设定当前号"
            message = f"「{name}」当前号设为（下一次从它的下一个开始）："
        current = str((self.book.data.get(name) or {}).get("last") or "")
        value, ok = QInputDialog.getText(self, title, message, text=current)
        if not ok:
            return
        self.book.set_last(name, value.strip())
        self._refresh_all_previews()

    def _on_accept(self) -> None:
        fields: Dict[str, str] = {}
        for row in range(self.table.rowCount()):
            check = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            seed_item = self.table.item(row, 2)
            if check and check.checkState() == Qt.Checked and name_item:
                fields[name_item.text()] = seed_item.text().strip() if seed_item else ""
        self.fields = fields
        self.accept()

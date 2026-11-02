"""历史数据窗口：按业务查看、搜索、回填。"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.history_store import delete_record, load_history, search_history


class HistoryDialog(QDialog):
    """浏览器历史风格的批量填充/单人数据历史。"""

    def __init__(self, business_name: str, parent=None):
        super().__init__(parent)
        self.business_name = business_name
        self.selected_record: Optional[Dict[str, Any]] = None
        self.records: List[Dict[str, Any]] = load_history(business_name)
        self.setWindowTitle(f"历史数据 · {business_name}")
        self.resize(820, 520)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel("点一条历史 → 填入当前变量 → 改完再点【一键生成】。只显示当前业务。")
        tip.setStyleSheet("color:#6b7280;")
        layout.addWidget(tip)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索："))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("姓名、证件号后四位、手机号……")
        self.search_edit.textChanged.connect(self._reload)
        search_row.addWidget(self.search_edit, 1)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "姓名", "证件后四位", "档案号", "输出目录"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self._on_fill())
        layout.addWidget(self.table, 1)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#6b7280;")
        layout.addWidget(self.count_label)

        buttons = QHBoxLayout()
        del_btn = QPushButton("删除选中")
        del_btn.setToolTip("只删除这条历史记录，不影响已生成的文档")
        del_btn.clicked.connect(self._on_delete)
        fill_btn = QPushButton("填入当前变量")
        fill_btn.setToolTip("把这条历史的数据填回主界面，不会自动生成")
        fill_btn.setObjectName("primary")
        fill_btn.clicked.connect(self._on_fill)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(del_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        buttons.addWidget(fill_btn)
        layout.addLayout(buttons)

    def _reload(self) -> None:
        self.records = search_history(self.business_name, self.search_edit.text())
        self.table.setRowCount(0)
        for record in self.records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            auto = record.get("auto_numbers", {}) or {}
            archive = "、".join(str(v) for v in auto.values() if str(v).strip())
            values = [
                str(record.get("time", "")),
                str(record.get("name", "")),
                str(record.get("id_tail", "")),
                archive,
                str(record.get("output_dir", "")),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, str(record.get("id", "")))
                self.table.setItem(row, column, item)
        self.count_label.setText(f"共 {len(self.records)} 条（最多保留 100 条/业务）")
        if self.records:
            self.table.selectRow(0)

    def _selected_record(self) -> Optional[Dict[str, Any]]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            return None
        return self.records[row]

    def _on_fill(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "提示", "请先选择一条历史记录")
            return
        self.selected_record = record
        self.accept()

    def _on_delete(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "提示", "请先选择一条历史记录")
            return
        ret = QMessageBox.question(
            self, "删除历史", "只删除这条历史记录，不影响已生成的文件。是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        delete_record(self.business_name, str(record.get("id", "")))
        self._reload()

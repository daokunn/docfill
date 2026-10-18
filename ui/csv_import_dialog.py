"""CSV 导入预览对话框。"""

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.csv_io import detect_header, parse_csv_rows, read_csv_file, rows_to_mapping


class CsvImportDialog(QDialog):
    """展示 CSV 前几行，让用户确认编码、表头和列映射。"""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CSV 导入预览")
        self.resize(620, 460)
        self.path = path
        self.text, self.encoding = read_csv_file(path)
        self.rows = parse_csv_rows(self.text)
        if not self.rows:
            raise ValueError("CSV 文件是空的，或没有可导入的行。")

        self.has_header = detect_header(self.rows)
        self.mapping = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"文件：{self.path}"))
        layout.addWidget(QLabel(
            f"编码：{self.encoding}；共 {len(self.rows)} 行。第一列=变量名，第二列=值。"
        ))

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["变量名", "值"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.header_check = QCheckBox("首行是表头（变量名,值），导入时跳过")
        self.header_check.setChecked(self.has_header)
        self.header_check.toggled.connect(self._on_header_toggled)
        layout.addWidget(self.header_check)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("导入")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._refresh_preview()

    def _on_header_toggled(self, checked: bool) -> None:
        self.has_header = checked
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        preview = self.rows[:6]
        self.table.setRowCount(0)
        for row in preview:
            index = self.table.rowCount()
            self.table.insertRow(index)
            for column in range(2):
                value = row[column] if column < len(row) else ""
                item = QTableWidgetItem(value)
                if self.has_header and index == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(index, column, item)

    def _on_accept(self) -> None:
        mapping = rows_to_mapping(self.rows, self.has_header)
        if not mapping:
            QMessageBox.warning(
                self, "没有可导入的数据",
                "没有解析到「变量名,值」数据，请检查列顺序或取消“首行是表头”。",
            )
            return
        self.mapping = mapping
        self.accept()

"""目录设置：把模板目录、输出目录、重名策略收进一个窗口。

主界面只保留一行路径摘要和一个「目录设置…」按钮，避免顶部占掉变量表高度。
路径框是可编辑下拉框：默认带出当前业务上次用的目录，下拉里是所有业务的近期目录，
也可以直接手输路径。
"""

from typing import List

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout,
)

STRATEGIES = [
    ("重名时追加序号（推荐）", "append_seq"),
    ("重名时覆盖旧文件", "overwrite"),
    ("重名时跳过", "skip"),
]


class DirectoryDialog(QDialog):
    """模板目录 / 输出目录 / 重名策略。"""

    def __init__(self, template_dir: str, output_dir: str, strategy: str,
                 parent=None, business_name: str = "",
                 recent_templates: List[str] = None,
                 recent_outputs: List[str] = None):
        super().__init__(parent)
        self.setWindowTitle(
            f"目录设置 · {business_name}" if business_name else "目录设置")
        self.resize(760, 300)
        self.strategy = strategy or "append_seq"
        self.business_name = business_name
        self.recent_templates = list(recent_templates or [])
        self.recent_outputs = list(recent_outputs or [])
        self._build_ui(template_dir, output_dir)

    def _path_combo(self, current: str, recent: List[str], placeholder: str):
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(420)
        combo.setToolTip("可以从下拉里选近期用过的目录，也可以直接输入完整路径")
        values = [str(v) for v in [current] + list(recent) if str(v).strip()]
        unique = []
        for value in values:
            if value not in unique:
                unique.append(value)
        combo.addItems(unique)
        combo.setCurrentText(str(current or ""))
        if combo.lineEdit():
            combo.lineEdit().setPlaceholderText(placeholder)
        return combo

    def _build_ui(self, template_dir: str, output_dir: str) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel(
            "模板目录放原始模板；输出目录放生成结果，两个目录不要互相嵌套。\n"
            "下拉框里是当前业务和所有业务的近期目录，可直接选，也可手动输入路径。")
        tip.setStyleSheet("color:#6b7280;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addWidget(QLabel("模板目录（每个子文件夹 = 一项业务）："))
        row1 = QHBoxLayout()
        self.template_combo = self._path_combo(
            template_dir, self.recent_templates, "选择或输入模板根目录")
        self.template_edit = self.template_combo.lineEdit()
        btn1 = QPushButton("选择…")
        btn1.setToolTip("浏览选择模板根目录；会从当前路径开始")
        btn1.clicked.connect(self._pick_template)
        row1.addWidget(self.template_combo, 1)
        row1.addWidget(btn1)
        layout.addLayout(row1)

        layout.addWidget(QLabel("输出目录（生成结果放这里）："))
        row2 = QHBoxLayout()
        self.output_combo = self._path_combo(
            output_dir, self.recent_outputs, "选择或输入输出根目录")
        self.output_edit = self.output_combo.lineEdit()
        btn2 = QPushButton("选择…")
        btn2.setToolTip("浏览选择输出根目录；会从当前路径开始")
        btn2.clicked.connect(self._pick_output)
        row2.addWidget(self.output_combo, 1)
        row2.addWidget(btn2)
        layout.addLayout(row2)

        layout.addWidget(QLabel("重名策略："))
        self.strategy_combo = QComboBox()
        for label, value in STRATEGIES:
            self.strategy_combo.addItem(label, value)
        index = self.strategy_combo.findData(self.strategy)
        self.strategy_combo.setCurrentIndex(max(index, 0))
        layout.addWidget(self.strategy_combo)
        layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _pick_template(self) -> None:
        start = self.template_combo.currentText().strip()
        path = QFileDialog.getExistingDirectory(self, "选择模板根目录", start)
        if path:
            self.template_combo.setCurrentText(path)

    def _pick_output(self) -> None:
        start = self.output_combo.currentText().strip()
        path = QFileDialog.getExistingDirectory(self, "选择输出根目录", start)
        if path:
            self.output_combo.setCurrentText(path)

    def values(self):
        return (
            self.template_combo.currentText().strip(),
            self.output_combo.currentText().strip(),
            self.strategy_combo.currentData() or "append_seq",
        )

"""目录设置：把模板目录、输出目录、重名策略收进一个窗口。

主界面只保留一行路径摘要和一个「目录设置…」按钮，避免顶部占掉变量表高度。
"""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

STRATEGIES = [
    ("重名时追加序号（推荐）", "append_seq"),
    ("重名时覆盖旧文件", "overwrite"),
    ("重名时跳过", "skip"),
]


class DirectoryDialog(QDialog):
    """模板目录 / 输出目录 / 重名策略。"""

    def __init__(self, template_dir: str, output_dir: str, strategy: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("目录设置")
        self.resize(680, 260)
        self.strategy = strategy or "append_seq"
        self._build_ui(template_dir, output_dir)

    def _build_ui(self, template_dir: str, output_dir: str) -> None:
        layout = QVBoxLayout(self)
        tip = QLabel("模板目录放原始模板；输出目录放生成结果，两个目录不要互相嵌套。")
        tip.setStyleSheet("color:#6b7280;")
        layout.addWidget(tip)

        layout.addWidget(QLabel("模板目录（每个子文件夹 = 一项业务）："))
        row1 = QHBoxLayout()
        self.template_edit = QLineEdit(template_dir)
        self.template_edit.setPlaceholderText("选择放模板的文件夹")
        btn1 = QPushButton("选择…")
        btn1.setToolTip("选择存放原始模板的文件夹")
        btn1.clicked.connect(self._pick_template)
        row1.addWidget(self.template_edit, 1)
        row1.addWidget(btn1)
        layout.addLayout(row1)

        layout.addWidget(QLabel("输出目录（生成结果放这里）："))
        row2 = QHBoxLayout()
        self.output_edit = QLineEdit(output_dir)
        self.output_edit.setPlaceholderText("选择放生成结果的文件夹")
        btn2 = QPushButton("选择…")
        btn2.setToolTip("选择生成结果要保存到的文件夹，不要放在模板目录里面")
        btn2.clicked.connect(self._pick_output)
        row2.addWidget(self.output_edit, 1)
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
        path = QFileDialog.getExistingDirectory(self, "选择模板根目录")
        if path:
            self.template_edit.setText(path)

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出根目录")
        if path:
            self.output_edit.setText(path)

    def values(self):
        return (
            self.template_edit.text().strip(),
            self.output_edit.text().strip(),
            self.strategy_combo.currentData() or "append_seq",
        )

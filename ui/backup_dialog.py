"""导出配置包选项。"""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)


class BackupOptionsDialog(QDialog):
    """勾选是否把历史数据一起备份。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出配置包")
        self.resize(520, 220)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择要备份的内容："))

        self.history_checkbox = QCheckBox("包含历史数据")
        self.history_checkbox.setChecked(True)
        self.history_checkbox.setToolTip(
            "历史数据只包含变量值和档案号，不包含生成的文档，通常只有几百 KB")
        layout.addWidget(self.history_checkbox)

        self.rest_checkbox = QCheckBox("设置 / 别名 / 自定义规则 / 名单 / 编号台账")
        self.rest_checkbox.setChecked(True)
        self.rest_checkbox.setEnabled(False)
        self.rest_checkbox.setToolTip("这些基础配置始终包含在配置包里")
        layout.addWidget(self.rest_checkbox)

        note = QLabel("不包含：模板文件、已生成的 Word/Excel 文件。")
        note.setStyleSheet("color:#6b7280; font-size:9pt;")
        layout.addWidget(note)
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("下一步")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def include_history(self) -> bool:
        return self.history_checkbox.isChecked()

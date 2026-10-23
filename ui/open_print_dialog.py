"""生成后打开文件 / 自动打印的配置对话框。"""

from typing import Dict, List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout,
)
try:
    from PySide6.QtPrintSupport import QPrinterInfo
except Exception:  # 精简版 Qt 可能没带 printsupport
    QPrinterInfo = None

MODES = [
    ("打开本次全部文件", "all"),
    ("只打开第一个文件", "first"),
    ("只打开指定模板的文件（可多选）", "specified"),
]


class OpenPrintDialog(QDialog):
    """配置生成后自动打开哪些文件、是否自动打印。"""

    def __init__(self, settings: Dict[str, object],
                 templates: Sequence[Dict[str, str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("打开与打印设置")
        self.resize(720, 560)
        self.settings = dict(settings or {})
        # [{"name": 显示名, "rel_path": 唯一键}]
        self.templates = list(templates or [])
        self.result_config: Dict[str, object] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel(
            "这些动作只在【设置】里开启「生成后自动打开输出文件夹」时生效。\n"
            "打印使用系统默认打印机：Windows 走文件关联的 print 动作，Linux 走 lp/lpr。\n"
            "文件会保持打开状态，打印完成后不会自动关闭。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#374151;")
        layout.addWidget(tip)

        self.open_checkbox = QCheckBox("生成后自动打开文件")
        self.open_checkbox.setChecked(bool(self.settings.get("open_generated_files", False)))
        layout.addWidget(self.open_checkbox)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("打开范围："))
        self.mode_combo = QComboBox()
        for label, value in MODES:
            self.mode_combo.addItem(label, value)
        current_mode = str(self.settings.get("open_files_mode", "all") or "all")
        index = self.mode_combo.findData(current_mode)
        self.mode_combo.setCurrentIndex(max(index, 0))
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        layout.addWidget(QLabel("指定模板（勾选后，每次生成只打开这些模板产出的新文件）："))
        self.template_list = QListWidget()
        selected = set(self.settings.get("open_files_templates", []) or [])
        if self.templates:
            for item in self.templates:
                name = str(item.get("name") or "")
                rel_path = str(item.get("rel_path") or name)
                row = QListWidgetItem(name)
                row.setData(Qt.UserRole, rel_path)
                row.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                row.setCheckState(Qt.Checked if rel_path in selected else Qt.Unchecked)
                self.template_list.addItem(row)
        else:
            row = QListWidgetItem("（当前没有扫描到模板，请先选择业务）")
            row.setFlags(Qt.NoItemFlags)
            self.template_list.addItem(row)
        self.template_list.setMinimumHeight(180)
        layout.addWidget(self.template_list, 1)

        self.print_checkbox = QCheckBox("打开后自动打印")
        self.print_checkbox.setChecked(bool(self.settings.get("auto_print_after_open", False)))
        layout.addWidget(self.print_checkbox)

        self.silent_checkbox = QCheckBox("静默打印（不弹打印对话框）")
        self.silent_checkbox.setChecked(bool(self.settings.get("silent_print", True)))
        layout.addWidget(self.silent_checkbox)

        print_row = QHBoxLayout()
        print_row.addWidget(QLabel("打印机："))
        self.printer_combo = QComboBox()
        self.printer_combo.addItem("系统默认打印机", "")
        if QPrinterInfo is not None:
            try:
                for info in QPrinterInfo.availablePrinters():
                    self.printer_combo.addItem(info.printerName(), info.printerName())
            except Exception:
                pass
        saved_printer = str(self.settings.get("printer_name", "") or "")
        printer_index = self.printer_combo.findData(saved_printer)
        if printer_index < 0 and saved_printer:
            self.printer_combo.addItem(saved_printer, saved_printer)
            printer_index = self.printer_combo.count() - 1
        self.printer_combo.setCurrentIndex(max(printer_index, 0))
        print_row.addWidget(self.printer_combo, 1)
        print_row.addWidget(QLabel("份数："))
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 50)
        try:
            self.copies_spin.setValue(int(self.settings.get("print_copies", 1) or 1))
        except (TypeError, ValueError):
            self.copies_spin.setValue(1)
        print_row.addWidget(self.copies_spin)
        layout.addLayout(print_row)

        note = QLabel(
            "提示：静默打印是否真正不弹框，取决于本机默认打印机和文件关联程序；\n"
            "本程序不会再额外弹打印设置窗口。批量打开/打印很多文件会占用较多系统资源。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280; font-size:9pt;")
        layout.addWidget(note)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.mode_combo.currentIndexChanged.connect(self._sync_enabled)
        self.open_checkbox.toggled.connect(self._sync_enabled)
        self.print_checkbox.toggled.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        open_on = self.open_checkbox.isChecked()
        self.mode_combo.setEnabled(open_on)
        self.template_list.setEnabled(open_on and self.mode_combo.currentData() == "specified")
        self.print_checkbox.setEnabled(open_on)
        self.silent_checkbox.setEnabled(open_on and self.print_checkbox.isChecked())

    def _selected_templates(self) -> List[str]:
        chosen: List[str] = []
        for row in range(self.template_list.count()):
            item = self.template_list.item(row)
            if item is None or item.flags() == Qt.NoItemFlags:
                continue
            if item.checkState() == Qt.Checked:
                chosen.append(str(item.data(Qt.UserRole) or item.text()))
        return chosen

    def _on_accept(self) -> None:
        self.result_config = {
            "open_generated_files": self.open_checkbox.isChecked(),
            "open_files_mode": self.mode_combo.currentData() or "all",
            "open_files_templates": self._selected_templates(),
            "auto_print_after_open": self.print_checkbox.isChecked(),
            "silent_print": self.silent_checkbox.isChecked(),
            "printer_name": self.printer_combo.currentData() or "",
            "print_copies": int(self.copies_spin.value()),
        }
        self.accept()

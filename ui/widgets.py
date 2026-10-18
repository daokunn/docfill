"""小型 Qt 控件扩展。"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QTableWidget


class VariableTableWidget(QTableWidget):
    """支持从 Excel/CSV 整列粘贴的变量表。

    普通单格粘贴保持 Qt 默认行为；多行/多列文本通过 ``bulk_paste``
    信号交给主窗口处理。
    """

    bulk_paste = Signal(str, int)

    def keyPressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.matches(QKeySequence.Paste):
            text = QApplication.clipboard().text()
            if "\n" in text.strip() or "\t" in text:
                self.bulk_paste.emit(text, self.currentRow())
                return
        super().keyPressEvent(event)

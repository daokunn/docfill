"""小型 Qt 控件扩展。"""

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QDrag, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QLineEdit, QStyledItemDelegate,
    QTableWidget,
)

_ROW_MIME = "application/x-docfill-variable-row"


class InlineEditDelegate(QStyledItemDelegate):
    """原地编辑：编辑中的行由外面放大/高亮，回车/Tab 交给外部跳转。"""

    editStarted = Signal(int, int)
    editFinished = Signal(int, int)
    moveRequested = Signal(int, int, str)  # (row, col, tab/enter/backtab)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing = (-1, -1)

    def createEditor(self, parent, option, index):  # noqa: N802
        self._editing = (index.row(), index.column())
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            font = QFont()
            font.setPointSizeF(14)
            editor.setFont(font)
            editor.setMinimumHeight(38)
            editor.setStyleSheet("padding: 6px;")
        editor.installEventFilter(self)
        self.editStarted.emit(index.row(), index.column())
        return editor

    def destroyEditor(self, editor, index):  # noqa: N802
        self.editFinished.emit(index.row(), index.column())
        super().destroyEditor(editor, index)

    def eventFilter(self, editor, event):  # noqa: N802
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
                self.moveRequested.emit(self._editing[0], self._editing[1], "enter")
                return True
            if key == Qt.Key_Tab:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
                self.moveRequested.emit(self._editing[0], self._editing[1], "tab")
                return True
            if key == Qt.Key_Backtab:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
                self.moveRequested.emit(self._editing[0], self._editing[1], "backtab")
                return True
        return super().eventFilter(editor, event)


class VariableTableWidget(QTableWidget):
    """支持从 Excel/CSV 整列粘贴、可拖拽排序的变量表。

    普通单格粘贴保持 Qt 默认行为；多行/多列文本通过 ``bulk_paste``
    信号交给主窗口处理。拖动整行后发出 ``row_dropped(源行, 目标行)``。
    """

    bulk_paste = Signal(str, int)
    row_dropped = Signal(int, int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.viewport().setAcceptDrops(True)
        self._drop_target = -1
        self._drop_indicator = QFrame(self.viewport())
        self._drop_indicator.setObjectName("dropIndicator")
        self._drop_indicator.setStyleSheet(
            "QFrame#dropIndicator { background:#2563eb; border-radius:2px; }")
        self._drop_indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drop_indicator.hide()

    def _target_at(self, pos: QPoint):
        """返回 (插入位置, 画线 y)；指针在行的下半部分表示插到该行之后。"""
        index = self.indexAt(pos)
        if index.isValid():
            rect = self.visualRect(index)
            before = pos.y() < rect.center().y()
            target = index.row() if before else index.row() + 1
            y = rect.top() if before else rect.bottom()
            return target, y
        return self.rowCount(), self.viewport().height() - 1

    def _show_drop_indicator(self, target: int, y: int) -> None:
        self._drop_target = target
        self._drop_indicator.setGeometry(
            0, max(0, y - 1), self.viewport().width(), 3)
        self._drop_indicator.raise_()
        self._drop_indicator.show()

    def _hide_drop_indicator(self) -> None:
        self._drop_target = -1
        self._drop_indicator.hide()

    def startDrag(self, supportedActions):  # noqa: N802 - Qt 命名
        """用整行截图作为拖动卡片，并携带行号；不交给表格默认覆盖逻辑。"""
        indexes = self.selectedIndexes()
        if not indexes:
            return
        row = indexes[0].row()
        self.selectRow(row)
        y = self.rowViewportPosition(row)
        height = self.rowHeight(row)
        rect = QRect(0, y, self.viewport().width(), height)
        pixmap = self.viewport().grab(rect)

        mime = QMimeData()
        mime.setData(_ROW_MIME, str(row).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(16, max(4, height // 2)))
        drag.exec(Qt.MoveAction)
        self._hide_drop_indicator()

    def dragEnterEvent(self, event):  # noqa: N802 - Qt 命名
        if event.mimeData().hasFormat(_ROW_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802 - Qt 命名
        if event.mimeData().hasFormat(_ROW_MIME):
            target, y = self._target_at(event.position().toPoint())
            self._show_drop_indicator(target, y)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):  # noqa: N802 - Qt 命名
        self._hide_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802 - Qt 命名
        if not event.mimeData().hasFormat(_ROW_MIME):
            super().dropEvent(event)
            return
        try:
            source = int(bytes(event.mimeData().data(_ROW_MIME)).decode("utf-8"))
        except (TypeError, ValueError):
            self._hide_drop_indicator()
            return
        if self._drop_target >= 0:
            target = self._drop_target
        else:
            target, _y = self._target_at(event.position().toPoint())
        self._hide_drop_indicator()
        event.acceptProposedAction()
        # 真正移动数据由主窗口完成，表格不参与覆盖/删除，源行绝不会空白
        self.row_dropped.emit(source, target)

    def keyPressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.matches(QKeySequence.Paste):
            text = QApplication.clipboard().text()
            if "\n" in text.strip() or "\t" in text:
                self.bulk_paste.emit(text, self.currentRow())
                return
        super().keyPressEvent(event)

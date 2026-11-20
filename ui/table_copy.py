"""表格复制：单元格、整行、整列、选中区域。"""

from typing import List, Optional

from PySide6.QtWidgets import QApplication, QTableWidget


def _item_text(table: QTableWidget, row: int, col: int) -> str:
    item = table.item(row, col)
    return item.text() if item is not None else ""


def row_text(table: QTableWidget, row: int) -> str:
    return "\t".join(_item_text(table, row, col)
                     for col in range(table.columnCount()))


def column_text(table: QTableWidget, col: int) -> str:
    rows = []
    for row in range(table.rowCount()):
        if table.isRowHidden(row):
            continue
        rows.append(_item_text(table, row, col))
    return "\n".join(rows)


def selection_text(table: QTableWidget) -> str:
    ranges = table.selectedRanges()
    if not ranges:
        row, col = table.currentRow(), table.currentColumn()
        if row < 0:
            return ""
        return _item_text(table, row, col)
    lines: List[str] = []
    for rng in ranges:
        for row in range(rng.topRow(), rng.bottomRow() + 1):
            if table.isRowHidden(row):
                continue
            cells = [_item_text(table, row, col)
                     for col in range(rng.leftColumn(), rng.rightColumn() + 1)]
            lines.append("\t".join(cells))
    return "\n".join(lines)


def copy_text(text: str) -> bool:
    text = str(text or "")
    if not text:
        return False
    QApplication.clipboard().setText(text)
    return True


def copy_table(table: QTableWidget, mode: str = "selection",
               row: Optional[int] = None, col: Optional[int] = None) -> bool:
    if mode == "row" and row is not None:
        return copy_text(row_text(table, row))
    if mode == "column" and col is not None:
        return copy_text(column_text(table, col))
    if mode == "cell" and row is not None and col is not None:
        return copy_text(_item_text(table, row, col))
    return copy_text(selection_text(table))

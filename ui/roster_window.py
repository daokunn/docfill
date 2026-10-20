"""人员名单窗口（独立窗口）。

阶段一主干：宽表导入 → 名单显示 → 手动编辑 → 生成选中。
数据即时落盘，关软件不丢；主键默认姓名，重名一并标红提示。
"""

import os
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from core.roster import (
    STATUS_GENERATED,
    STATUS_PENDING,
    Roster,
    load_roster,
)
from core.table_import import TableImportError, read_table_file, rows_to_dicts
from output.roster_export import default_file_name, export_to_xlsx, write_template_xlsx

# 状态底色，和导出 Excel 保持一致的语义
_COLOR_PENDING = QColor("#fff7cc")     # 待补充：淡黄
_COLOR_READY = QColor("#ffffff")       # 已填完：白
_COLOR_GENERATED = QColor("#e8f5e9")   # 已生成：淡绿
_COLOR_DUP = QColor("#fde2e2")         # 重名行：淡红


class RosterWindow(QWidget):
    """某个业务的名单窗口。

    :param business_name: 业务名（决定持久化文件）
    :param template_vars: 模板变量顺序（列顺序、必填计算用）
    :param optional_vars: 可选变量集合（{{备注?}}）
    :param generate_one: 回调，传入一个人的 {变量: 值}，返回 (成功数, 失败数)
    :param parent: 父窗口
    """

    def __init__(self, business_name: str, template_vars: List[str],
                 optional_vars: List[str], generate_one: Callable[[Dict[str, str]], tuple],
                 open_output: Optional[Callable[[], None]] = None,
                 auto_open_output: bool = True,
                 parent=None):
        super().__init__(parent, Qt.Window)
        self.business_name = business_name
        self.template_vars = [str(v).strip() for v in template_vars if str(v).strip()]
        self.optional_vars = set(str(v).strip() for v in optional_vars if str(v).strip())
        self.generate_one = generate_one
        self.open_output = open_output
        self.auto_open_output = auto_open_output

        self.roster: Roster = load_roster(business_name)
        # 名单为空时先按模板建列，导入/新增都有稳定列顺序
        if not self.roster.columns:
            self.roster.ensure_columns(self.template_vars)
        self._required = self.roster.required_fields(self.template_vars, list(self.optional_vars))
        self.roster.refresh_status(self._required)

        self.setWindowTitle(f"人员名单 · {business_name}")
        self.resize(1080, 640)
        self._build_ui()
        self._reload_table()

    # ---------- 界面 ----------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel("第一行是变量标题，接下来每行一个人。改完自动保存，关软件不丢。")
        tip.setStyleSheet("color:#6b7280;")
        layout.addWidget(tip)

        toolbar = QHBoxLayout()
        btn_import = QPushButton("导入名单（Excel/CSV）")
        btn_import.clicked.connect(self._on_import)
        btn_template = QPushButton("下载空模板（多人）")
        btn_template.setToolTip("导出第一行是变量名、之后每行一个人的 Excel 模板")
        btn_template.clicked.connect(self._on_download_template)
        btn_add = QPushButton("新增一行")
        btn_add.clicked.connect(self._on_add_row)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._on_delete_rows)
        btn_export = QPushButton("导出名单")
        btn_export.clicked.connect(self._on_export)
        btn_gen = QPushButton("生成选中文档")
        btn_gen.setObjectName("primary")
        btn_gen.clicked.connect(self._on_generate_selected)
        for b in (btn_import, btn_template, btn_add, btn_del, btn_export, btn_gen):
            toolbar.addWidget(b)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索："))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入姓名/证件号等，边输边筛；清空即显示全部")
        self.search_edit.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search_edit, 1)

        # 匹配依据列（主键）：默认姓名，可切换为学号/身份证号等任意列。
        # 它决定重名判定、导入合并按哪一列对齐、生成时的目录命名兜底。
        search_row.addWidget(QLabel("匹配依据："))
        self.key_combo = QComboBox()
        self.key_combo.setToolTip(
            "名单靠哪一列区分不同的人。\n"
            "默认「姓名」；若常出现重名，可改用「学号」「身份证号」等唯一列。")
        self.key_combo.currentIndexChanged.connect(self._on_key_changed)
        search_row.addWidget(self.key_combo)
        layout.addLayout(search_row)

        font = QFont()
        font.setPointSizeF(11.5)
        self.table = QTableWidget(0, 0)
        self.table.setFont(font)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#374151;")
        layout.addWidget(self.status_label)

    # ---------- 表格刷新 ----------

    def _reload_table(self) -> None:
        columns = self.roster.columns or self.template_vars
        dup_keys = self.roster.duplicate_keys()

        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(self.roster.rows))
        for r, row in enumerate(self.roster.rows):
            is_dup = row.key_value(self.roster.key_field) in dup_keys
            for c, name in enumerate(columns):
                item = QTableWidgetItem(str(row.values.get(name, "") or ""))
                bg = self._row_color(row, is_dup, self._required)
                if bg is not None:
                    item.setBackground(bg)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

        self._update_status_bar()
        self._apply_filter()

    @staticmethod
    def _row_color(row, is_dup: bool, required: List[str]) -> Optional[QColor]:
        if is_dup:
            return _COLOR_DUP
        if row.status == STATUS_GENERATED:
            return _COLOR_GENERATED
        if row.missing_fields(required):
            return _COLOR_PENDING
        return None

    def _update_status_bar(self) -> None:
        counts = self.roster.counts(self._required)
        dups = self.roster.duplicate_keys()
        text = (f"共 {counts['total']} 人｜待补充 {counts['pending']}｜"
                f"已填完 {counts['ready']}｜已生成 {counts['generated']}")
        if dups:
            names = "、".join(list(dups.keys())[:6]) + ("…" if len(dups) > 6 else "")
            text += f"　⚠ 重名：{names}"
        self.status_label.setText(text)
        self._refresh_key_combo()

    def _refresh_key_combo(self) -> None:
        """把当前所有列填进「匹配依据」下拉框，并保持选中主键。"""
        columns = self.roster.columns or self.template_vars
        current = self.roster.key_field
        self.key_combo.blockSignals(True)
        self.key_combo.clear()
        for name in columns:
            self.key_combo.addItem(name, name)
        idx = self.key_combo.findData(current)
        if idx < 0 and current:
            self.key_combo.addItem(current, current)
            idx = self.key_combo.count() - 1
        self.key_combo.setCurrentIndex(max(idx, 0))
        self.key_combo.blockSignals(False)

    def _on_key_changed(self, _index: int) -> None:
        """用户切换匹配依据列：立即生效并重绘（重名高亮会随之变化）。"""
        new_key = self.key_combo.currentData()
        if not new_key or new_key == self.roster.key_field:
            return
        self.roster.set_key_field(str(new_key))
        self.roster.refresh_status(self._required)
        self.roster.save()
        # 重算必填：若新主键列本身是模板变量，它仍是必填；这里保持原必填集合不变
        self._reload_table()

    # ---------- 事件 ----------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        columns = self.roster.columns or self.template_vars
        if item.column() >= len(columns):
            return
        name = columns[item.column()]
        self.roster.set_value(item.row(), name, item.text())
        self.roster.refresh_status(self._required)
        if not self.roster.save():
            QMessageBox.warning(self, "保存失败", self.roster.load_error or "名单未能保存")
        self._update_status_bar()

    def _on_import(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择名单文件", "", "表格文件 (*.xlsx *.xlsm *.csv *.txt)")
        if not path:
            return
        try:
            header, rows, note, warnings = read_table_file(path)
        except TableImportError as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return

        dicts = rows_to_dicts(header, rows)
        result = self.roster.merge_rows(dicts)
        self.roster.refresh_status(self._required)

        # 本次文件里删掉的列（如你把"名字"改成别的），名单默认仍保留会残留空列。
        # 检测到就问一下要不要一起清掉，避免越用越多僵尸列。
        gone = self.roster.missing_columns(header)
        removed_cols: List[str] = []
        if gone:
            ret = QMessageBox.question(
                self, "发现已删除的列",
                "名单里有这些列在本次文件中不存在：\n"
                + "、".join(gone[:10]) + ("…" if len(gone) > 10 else "")
                + "\n\n是否一并从名单中删除？\n（选「否」则保留，仅本次不更新它们）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.roster.drop_columns(gone)
                removed_cols = gone

        if not self.roster.save():
            QMessageBox.warning(self, "保存失败", self.roster.load_error or "名单未能保存")
        self._reload_table()

        report = [f"来源：{note}", f"读到 {len(rows)} 行", result.summary()]
        if removed_cols:
            report.append(f"已删除列：{'、'.join(removed_cols)}")
        if warnings:
            report.append("")
            report.extend(warnings[:5])
        if result.has_issues:
            report.append("")
            report.extend(result.detail_lines())
        QMessageBox.information(self, "导入完成", "\n".join(report))

    def _on_download_template(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存名单模板", default_file_name(self.business_name, "模板"),
            "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            write_template_xlsx(path, self.roster.columns or self.template_vars,
                                key_field=self.roster.key_field)
            QMessageBox.information(self, "已导出", f"空模板已保存：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _on_add_row(self) -> None:
        self.roster.add_row()
        self.roster.refresh_status(self._required)
        self.roster.save()
        self._reload_table()

    def _on_delete_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要删除的行")
            return
        ret = QMessageBox.question(
            self, "确认删除", f"将删除 {len(rows)} 行，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self.roster.remove_rows(rows)
        self.roster.refresh_status(self._required)
        self.roster.save()
        self._reload_table()

    def _on_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出名单", default_file_name(self.business_name), "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            count = export_to_xlsx(self.roster, path, required=self._required)
            QMessageBox.information(self, "已导出", f"已导出 {count} 人到：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _on_generate_selected(self) -> None:
        selected = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not selected:
            QMessageBox.information(self, "提示", "请先选中要生成的人（可多选）")
            return
        records = self.roster.selected_dicts(selected)
        total_ok = total_fail = 0
        done_rows: List[int] = []
        dirs: Dict[int, str] = {}
        for offset, record in enumerate(records):
            ok, fail = self.generate_one(record)
            total_ok += ok
            total_fail += fail
            if ok:
                done_rows.append(selected[offset])
                dirs[selected[offset]] = getattr(self, "_last_dir_hint", "")
        if done_rows:
            self.roster.mark_generated(done_rows, dirs)
            self.roster.save()
            self._reload_table()

        # 生成成功且开了自动打开，就直接弹出输出目录
        if total_ok and self.auto_open_output and self.open_output:
            try:
                self.open_output()
            except Exception:
                pass
        QMessageBox.information(
            self, "生成完成",
            f"选中 {len(records)} 人：成功 {total_ok} 个文件，失败 {total_fail} 个。")

    # ---------- 筛选 ----------

    def _apply_filter(self) -> None:
        keyword = self.search_edit.text().strip()
        hits = set(self.roster.search(keyword)) if keyword else None
        for r in range(self.table.rowCount()):
            visible = True if hits is None else (r in hits)
            self.table.setRowHidden(r, not visible)

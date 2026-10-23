"""人员名单窗口（独立窗口）。

阶段一主干：宽表导入 → 名单显示 → 手动编辑 → 生成选中。
数据即时落盘，关软件不丢；主键默认姓名，重名一并标红提示。
"""

import os
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.roster import (
    STATUS_GENERATED,
    STATUS_PENDING,
    STATUS_READY,
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
                 output_dir: str = "",
                 handover_enabled: bool = True,
                 handover_template: str = "",
                 handover_dedup_field: str = "姓名",
                 number_hint: Optional[Callable[[], str]] = None,
                 on_files: Optional[Callable[[], None]] = None,
                 parent=None):
        super().__init__(parent, Qt.Window)
        self.business_name = business_name
        self.template_vars = [str(v).strip() for v in template_vars if str(v).strip()]
        self.optional_vars = set(str(v).strip() for v in optional_vars if str(v).strip())
        self.generate_one = generate_one
        self.open_output = open_output
        self.auto_open_output = auto_open_output
        self.output_dir = output_dir
        self.handover_enabled = handover_enabled
        self.handover_template = handover_template
        self.handover_dedup_field = handover_dedup_field or "姓名"
        self.number_hint = number_hint
        self.on_files = on_files

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
        btn_resume = QPushButton("只生成未生成的")
        btn_resume.setToolTip("跳过已标记生成的行，只补做剩下的（断点续跑）")
        btn_resume.clicked.connect(self._on_generate_pending)
        btn_next = QPushButton("下一位待补充")
        btn_next.setToolTip("跳到下一位还没填完的人，边补边看")
        btn_next.clicked.connect(self._on_next_pending)
        btn_copy = QPushButton("复制选中列")
        btn_copy.setToolTip("把选中的单元格复制到剪贴板，可直接粘回 Excel")
        btn_copy.clicked.connect(self._on_copy_selection)
        for b in (btn_import, btn_template, btn_add, btn_del, btn_export,
                  btn_gen, btn_resume, btn_next, btn_copy):
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

        search_row.addWidget(QLabel("状态："))
        self.status_combo = QComboBox()
        self.status_combo.addItem("全部", "")
        self.status_combo.addItem("待补充", STATUS_PENDING)
        self.status_combo.addItem("已填完", STATUS_READY)
        self.status_combo.addItem("已生成", STATUS_GENERATED)
        self.status_combo.currentIndexChanged.connect(self._apply_filter)
        search_row.addWidget(self.status_combo)
        layout.addLayout(search_row)

        self.number_label = QLabel("")
        self.number_label.setStyleSheet(
            "color:#2563eb; font-weight:bold; padding:2px 4px;")
        layout.addWidget(self.number_label)
        self._refresh_number_hint()

        font = QFont()
        font.setPointSizeF(11.5)
        self.table = QTableWidget(0, 0)
        self.table.setFont(font)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.itemChanged.connect(self._on_item_changed)
        # 列头右键：整列批量填同一个值（同一单位/日期/金额时最省事）
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(
            self._on_header_menu)
        # 表格右键：复制为新行（同单位只改姓名/证件号）
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#374151;")
        layout.addWidget(self.status_label)

        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        """录入键盘流：Tab/Enter/F2 用表格默认行为，额外加 Ctrl+C 复制、Ctrl+D 填今天。"""
        QShortcut(QKeySequence.Copy, self.table, activated=self._on_copy_selection)
        QShortcut(QKeySequence("Ctrl+D"), self.table, activated=self._on_fill_today)

    def _refresh_number_hint(self) -> None:
        """显示当前各自动编号字段的下一个号码（整理当前文件时可直接看到）。"""
        if not self.number_hint:
            return
        try:
            text = self.number_hint() or ""
        except Exception:
            text = ""
        self.number_label.setText(text)

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
        self._generate_rows(selected)

    def _on_generate_pending(self) -> None:
        """断点续跑：只处理状态不是"已生成"的行。"""
        pending = [i for i, row in enumerate(self.roster.rows)
                   if row.status != STATUS_GENERATED]
        if not pending:
            QMessageBox.information(self, "提示", "所有行都已生成，无需补做。")
            return
        ret = QMessageBox.question(
            self, "只生成未生成的",
            f"共 {len(self.roster.rows)} 人，其中 {len(pending)} 人尚未生成。\n是否只生成这 {len(pending)} 人？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ret == QMessageBox.Yes:
            self._generate_rows(pending)

    def _generate_rows(self, indexes: List[int]) -> None:
        """对给定行下标生成文档，更新状态，并按需写入移交清单台账。"""
        records = self.roster.selected_dicts(indexes)
        total_ok = total_fail = 0
        done_rows: List[int] = []
        failed_keys: set = set()
        dirs: Dict[int, str] = {}
        # 记录每人成功/失败，供台账状态列使用
        result_status: Dict[str, str] = {}

        for offset, (row_index, record) in enumerate(zip(indexes, records)):
            ok, fail = self.generate_one(record)
            total_ok += ok
            total_fail += fail
            key_value = str(record.get(self.handover_dedup_field, "") or "").strip()
            if ok:
                done_rows.append(row_index)
                dirs[row_index] = getattr(self, "_last_dir_hint", "")
                # 把本次实际发放的自动编号写回名单行，界面上能直接看到
                for name, value in record.items():
                    if name in self.roster.columns and str(value or "").strip():
                        self.roster.set_value(row_index, name, value)
                if key_value:
                    result_status[key_value] = "已生成"
            else:
                if key_value:
                    result_status[key_value] = "生成失败"
                failed_keys.add(key_value)

        if done_rows:
            self.roster.mark_generated(done_rows, dirs)
            self.roster.save()
            self._reload_table()

        # 移交清单：把本批人追加进台账（去重键命中旧行则更新）
        ledger_note = ""
        if self.handover_enabled and self.output_dir and records:
            try:
                from output.handover_ledger import append_batch
                path, added, updated, unmatched = append_batch(
                    self.output_dir, self.business_name, records,
                    template_path=self.handover_template,
                    dedup_field=self.handover_dedup_field,
                    status_by_key=result_status,
                )
                ledger_note = f"\n移交清单已追加：新增 {added} 人、更新 {updated} 人\n{path}"
                if unmatched:
                    ledger_note += ("\n⚠ 模板这些列没找到对应数据（请改表头或在别名表补映射）："
                                    + "、".join(unmatched[:8]))
            except Exception as exc:
                ledger_note = f"\n⚠ 移交清单写入失败：{exc}"

        if total_ok and self.auto_open_output and self.open_output:
            try:
                self.open_output()
            except Exception:
                pass
        self._refresh_number_hint()
        if total_ok and self.on_files:
            try:
                self.on_files()
            except Exception:
                pass
        QMessageBox.information(
            self, "生成完成",
            f"处理 {len(records)} 人：成功 {total_ok} 个文件，失败 {total_fail} 个。{ledger_note}")

    # ---------- 剪贴板 / 键盘辅助 ----------

    def _on_copy_selection(self) -> None:
        """把选中的单元格按行列结构复制到剪贴板，可直接粘回 Excel。"""
        ranges = self.table.selectedRanges()
        if not ranges:
            return
        lines: List[str] = []
        for rng in ranges:
            for row in range(rng.topRow(), rng.bottomRow() + 1):
                cells: List[str] = []
                for col in range(rng.leftColumn(), rng.rightColumn() + 1):
                    item = self.table.item(row, col)
                    cells.append(item.text() if item else "")
                lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def _on_fill_today(self) -> None:
        """对当前选中的日期类单元格填入今天（按名单存储格式 YYYY-MM-DD）。"""
        import datetime
        columns = self.roster.columns or self.template_vars
        today = datetime.date.today().strftime("%Y-%m-%d")
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        cols = sorted({idx.column() for idx in self.table.selectedIndexes()})
        filled = 0
        for r in rows:
            for c in cols:
                if c >= len(columns):
                    continue
                name = columns[c]
                if any(k in name for k in ("日期", "时间", "出生")):
                    item = self.table.item(r, c) or QTableWidgetItem()
                    item.setText(today)
                    self.table.setItem(r, c, item)
                    self.roster.set_value(r, name, today)
                    filled += 1
        if filled:
            self.roster.refresh_status(self._required)
            self.roster.save()
            self._update_status_bar()

    # ---------- 筛选 ----------

    def _apply_filter(self) -> None:
        keyword = self.search_edit.text().strip()
        hits = set(self.roster.search(keyword)) if keyword else None
        wanted = self.status_combo.currentData() if hasattr(self, "status_combo") else ""
        for r in range(self.table.rowCount()):
            visible = True if hits is None else (r in hits)
            if visible and wanted and r < len(self.roster.rows):
                visible = self.roster.rows[r].status == wanted
            self.table.setRowHidden(r, not visible)

    # ---------- 效率操作 ----------

    def _on_header_menu(self, pos) -> None:
        column = self.table.horizontalHeader().logicalIndexAt(pos)
        if column < 0:
            return
        columns = self.roster.columns or self.template_vars
        if column >= len(columns):
            return
        name = columns[column]
        menu = QMenu(self)
        act_fill = menu.addAction(f"整列填入同一值（{name}）…")
        act_clear = menu.addAction(f"清空整列（{name}）")
        chosen = menu.exec(self.table.horizontalHeader().mapToGlobal(pos))
        if chosen == act_fill:
            value, ok = QInputDialog.getText(self, "整列填充", f"把「{name}」整列都填成：")
            if ok:
                self._fill_column(column, value)
        elif chosen == act_clear:
            ret = QMessageBox.question(
                self, "清空整列", f"确定清空「{name}」整列？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.Yes:
                self._fill_column(column, "")

    def _fill_column(self, column: int, value: str) -> None:
        columns = self.roster.columns or self.template_vars
        name = columns[column]
        for row_index in range(len(self.roster.rows)):
            self.roster.set_value(row_index, name, value)
        self.roster.refresh_status(self._required)
        self.roster.save()
        self._reload_table()

    def _on_table_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        act_dup = menu.addAction("复制为新行")
        chosen = menu.exec(self.table.mapToGlobal(pos))
        if chosen == act_dup:
            self._duplicate_row(row)

    def _duplicate_row(self, row_index: int) -> None:
        """复制一个人为新行，只改姓名/证件号等差异项。"""
        if not 0 <= row_index < len(self.roster.rows):
            return
        source = self.roster.rows[row_index]
        self.roster.add_row(values=dict(source.values))
        self.roster.refresh_status(self._required)
        self.roster.save()
        self._reload_table()
        new_row = len(self.roster.rows) - 1
        if new_row >= 0:
            self.table.selectRow(new_row)
            self.table.scrollToBottom()

    def _on_next_pending(self) -> None:
        """跳到下一位还没填完的人，并直接定位到第一个空格。"""
        pending = [i for i, row in enumerate(self.roster.rows)
                   if row.status == STATUS_PENDING]
        if not pending:
            QMessageBox.information(self, "提示", "没有待补充的人了。")
            return
        current = self.table.currentRow()
        nxt = next((i for i in pending if i > current), pending[0])
        self.table.selectRow(nxt)
        self.table.scrollToItem(self.table.item(nxt, 0))
        columns = self.roster.columns or self.template_vars
        for col, name in enumerate(columns):
            if not str(self.roster.rows[nxt].values.get(name, "") or "").strip():
                item = self.table.item(nxt, col)
                if item:
                    self.table.setCurrentCell(nxt, col)
                    self.table.editItem(item)
                break


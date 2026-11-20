"""批量填充窗口（独立窗口）。

阶段一主干：宽表导入 → 名单显示 → 手动编辑 → 生成选中。
数据即时落盘，关软件不丢；主键默认姓名，重名一并标红提示。
"""

import os
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialogButtonBox, QFrame,
    QHBoxLayout, QHeaderView, QDialog, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QTextEdit,
    QCheckBox, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from config.settings import DEFAULT_SETTINGS
from core.roster import (
    STATUS_GENERATED,
    STATUS_PENDING,
    STATUS_READY,
    Roster,
)
from core.roster_batches import (
    active_roster, create_batch, delete_batch, list_batches,
    rename_batch, set_active_batch,
)
from ui.batch_set_dialog import BatchSetDialog
from ui.widgets import InlineEditDelegate
from ui.style import current_style
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
                 on_start: Optional[Callable[[], None]] = None,
                 settings=None,
                 formula_fields: Optional[List[str]] = None,
                 auto_fields: Optional[List[str]] = None,
                 resolve_record: Optional[Callable[[Dict[str, str]], Dict[str, str]]] = None,
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
        self.on_start = on_start
        self.settings = settings
        self.formula_fields = {str(name).strip() for name in (formula_fields or [])}
        self.auto_fields = {str(name).strip() for name in (auto_fields or [])}
        self._manual_numbers_by_row: Dict[int, Dict[str, str]] = {}
        self.resolve_record = resolve_record
        self._last_sort_column = -1
        self._last_sort_desc = False
        self._styled_column_count = -1

        self.roster: Roster = active_roster(business_name)
        self._prepare_roster()

        self.setStyleSheet(current_style())
        self.setWindowTitle(f"批量填充 · {business_name}")
        self.resize(1080, 640)
        self._build_ui()
        self._reload_table()

    def _prepare_roster(self) -> None:
        """当前批次名单载入后的统一处理（含损坏提示）。"""
        # 无条件补齐模板变量列：新业务首次打开时 Roster 默认只有主键列，
        # 若只在空列时补齐，编号等变量列会缺失，用户以为功能不存在。
        # ensure_columns 是追加语义，已有名单的自定义列不会丢。
        self.roster.ensure_columns(self.template_vars)
        self._required = self.roster.required_fields(
            self.template_vars, list(self.optional_vars))
        self.roster.refresh_status(self._required)
        if getattr(self.roster, "load_error", None):
            QMessageBox.warning(
                self, "名单数据需要检查",
                str(self.roster.load_error) +
                "\n\n为避免覆盖数据，请先检查备份文件；确认后仍可继续录入。")

    def _reload_batches(self, active_id: str = "") -> None:
        """重新载入批次列表并切到指定/当前批次。"""
        if active_id:
            set_active_batch(self.business_name, active_id)
        self._manual_numbers_by_row = {}
        self.roster = active_roster(self.business_name)
        self._prepare_roster()
        self._refresh_batch_combo()
        self._reload_table()
        self._refresh_number_hint()

    def refresh_template(self, template_vars: List[str],
                         optional_vars: List[str]) -> None:
        """模板重扫后同步列与必填集合，避免已开窗口继续用旧模板结构。"""
        self.template_vars = [str(v).strip() for v in template_vars if str(v).strip()]
        self.optional_vars = {str(v).strip() for v in optional_vars if str(v).strip()}
        self.roster.ensure_columns(self.template_vars)
        self._required = self.roster.required_fields(
            self.template_vars, list(self.optional_vars))
        self.roster.refresh_status(self._required)
        self.roster.save()
        self._reload_table()

    def _refresh_batch_combo(self) -> None:
        if not hasattr(self, "batch_combo"):
            return
        batches = list_batches(self.business_name)
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        for item in batches:
            self.batch_combo.addItem(item.get("name") or "未命名批次", item.get("id"))
        current = getattr(self.roster, "batch_id", "") or (
            batches[0].get("id") if batches else "")
        index = self.batch_combo.findData(current)
        if index >= 0:
            self.batch_combo.setCurrentIndex(index)
        self.batch_combo.blockSignals(False)

    # ---------- 界面 ----------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_card = QFrame()
        header_card.setObjectName("topCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(7)

        title_row = QHBoxLayout()
        title = QLabel("批量填充")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.roster_count_label = QLabel("0 人")
        self.roster_count_label.setObjectName("bizCount")
        title_row.addWidget(self.roster_count_label)
        header_layout.addLayout(title_row)

        tip = QLabel("第一行是变量标题，接下来每行一个人。改完自动保存，关软件不丢。")
        tip.setObjectName("sectionHint")
        header_layout.addWidget(tip)

        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("当前批次："))
        self.batch_combo = QComboBox()
        self.batch_combo.setToolTip("同一业务下可以保存多份名单，切换后互不影响")
        self.batch_combo.currentIndexChanged.connect(self._on_switch_batch)
        batch_row.addWidget(self.batch_combo, 1)
        for text, slot in (("新建", self._on_new_batch),
                           ("重命名", self._on_rename_batch),
                           ("删除", self._on_delete_batch)):
            button = QPushButton(text)
            button.setObjectName("ghost")
            button.clicked.connect(slot)
            batch_row.addWidget(button)
        header_layout.addLayout(batch_row)

        toolbar = QHBoxLayout()
        btn_import = QPushButton("导入名单（Excel/CSV）")
        btn_import.setToolTip("从 Excel/CSV 导入一批人：第一行是变量名，之后每行一个人")
        btn_import.clicked.connect(self._on_import)
        btn_template = QPushButton("下载空模板（多人）")
        btn_template.setToolTip("导出第一行是变量名、之后每行一个人的 Excel 模板")
        btn_template.clicked.connect(self._on_download_template)
        btn_add = QPushButton("新增一行")
        btn_add.setToolTip("手动新增一个人")
        btn_add.clicked.connect(self._on_add_row)
        btn_del = QPushButton("删除选中")
        btn_del.setToolTip("删除选中的行（进回收站，可恢复），不会删除已生成的文档")
        btn_del.clicked.connect(self._on_delete_rows)
        btn_trash = QPushButton("回收站")
        btn_trash.setToolTip("查看并恢复误删的行")
        btn_trash.clicked.connect(self._on_open_trash)
        btn_export = QPushButton("导出名单")
        btn_export.setToolTip("把当前批量填充表导出为 Excel，方便交接或补录")
        btn_export.clicked.connect(self._on_export)
        for b in (btn_import, btn_template, btn_add, btn_del, btn_trash, btn_export):
            b.setObjectName("ghost")
            toolbar.addWidget(b)
        toolbar.addStretch()
        header_layout.addLayout(toolbar)

        action_toolbar = QHBoxLayout()
        btn_gen = QPushButton("生成选中文档")
        btn_gen.setObjectName("primary")
        btn_gen.setToolTip("只给选中的这些人生成文档")
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
        btn_bulk = QPushButton("批量设值…")
        btn_bulk.setToolTip("给选中行/可见行统一设置某个字段，不用回 Excel 改模板")
        btn_bulk.clicked.connect(self._on_bulk_set)
        for b in (btn_gen, btn_resume, btn_next, btn_copy, btn_bulk):
            action_toolbar.addWidget(b)
        silent_on = bool(self.settings.get("silent_print", False)) if self.settings else False
        self.silent_print_label = QLabel(
            ("静默打印：开" if silent_on else "静默打印：关") + "（在【设置】里改）")
        self.silent_print_label.setStyleSheet("color:#6b7280; font-size:9pt;")
        self.silent_print_label.setToolTip(
            "静默打印是全局设置，统一在【设置 → 打印】里改。\n"
            "这里只显示当前状态，避免误以为只影响本窗口。")
        action_toolbar.addWidget(self.silent_print_label)
        action_toolbar.addStretch()
        header_layout.addLayout(action_toolbar)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchBox")
        self.search_edit.setPlaceholderText("搜索姓名、证件号等；清空显示全部")
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
        header_layout.addLayout(search_row)

        self.number_label = QLabel("")
        self.number_label.setStyleSheet(
            "color:#2563eb; font-weight:bold; padding:2px 4px;")
        header_layout.addWidget(self.number_label)
        layout.addWidget(header_card)
        self._refresh_number_hint()

        font = QFont()
        font.setPointSizeF(11.5)
        self.table = QTableWidget(0, 0)
        self.table.setFont(font)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self._inline_delegate = InlineEditDelegate(self.table)
        self.table.setItemDelegate(self._inline_delegate)
        self._inline_delegate.editStarted.connect(self._on_batch_edit_started)
        self._inline_delegate.editFinished.connect(self._on_batch_edit_finished)
        self._inline_delegate.moveRequested.connect(self._on_batch_move)
        self._inline_states = {}
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_sort_clicked)
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
        self.status_label.setObjectName("coveragePill")
        layout.addWidget(self.status_label)

        self._install_shortcuts()
        self._refresh_batch_combo()

    def _shortcuts(self) -> dict:
        """设置里的快捷键（缺省用出厂值），老配置自动补齐新键。"""
        values = dict(DEFAULT_SETTINGS.get("shortcuts", {}))
        if self.settings is not None:
            saved = self.settings.get("shortcuts", {}) or {}
            if isinstance(saved, dict):
                values.update(saved)
        return values

    def _typing_has_focus(self) -> bool:
        """编辑态不触发窗口快捷键，避免 Ctrl+D/Ctrl+I 抢走输入。"""
        from PySide6.QtWidgets import QPlainTextEdit
        widget = QApplication.focusWidget()
        return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox))

    def _guarded(self, slot):
        def wrapper():
            if self._typing_has_focus():
                return
            slot()
        return wrapper

    def _install_shortcuts(self) -> None:
        """录入快捷键：设置可改；编辑态自动让位给输入框。"""
        sc = self._shortcuts()
        pairs = [
            ("import", self._on_import),
            ("generate_selected", self._on_generate_selected),
            ("delete_rows", self._on_delete_rows),
            ("export", self._on_export),
            ("bulk_set", self._on_bulk_set),
        ]
        for key, slot in pairs:
            sequence = str(sc.get(key) or "").strip()
            if sequence:
                QShortcut(QKeySequence(sequence), self,
                          activated=self._guarded(slot))
        # 原有的两条录入快捷键保留，同样加焦点保护
        QShortcut(QKeySequence.Copy, self.table,
                  activated=self._guarded(self._on_copy_selection))
        QShortcut(QKeySequence("Ctrl+D"), self.table,
                  activated=self._guarded(self._on_fill_today))

    def _refresh_number_hint(self) -> None:
        """显示当前各自动编号字段的下一个号码（整理当前文件时可直接看到）。"""
        if not self.number_hint:
            return
        try:
            text = self.number_hint() or ""
        except Exception:
            text = ""
        self.number_label.setText(text)

    # ---------- 批次管理 ----------

    def _on_switch_batch(self, _index: int) -> None:
        batch_id = self.batch_combo.currentData()
        if not batch_id or batch_id == getattr(self.roster, "batch_id", ""):
            return
        self._reload_batches(str(batch_id))

    def _on_new_batch(self) -> None:
        name, ok = QInputDialog.getText(self, "新建批次", "批次名称：")
        if not ok or not name.strip():
            return
        batch = create_batch(
            self.business_name, name.strip(),
            columns=self.roster.columns or self.template_vars,
            key_field=self.roster.key_field,
        )
        self._reload_batches(batch["id"])
        self.status_label.setText(f"已新建批次：{batch['name']}")

    def _on_rename_batch(self) -> None:
        batch_id = getattr(self.roster, "batch_id", "")
        if not batch_id:
            return
        old = getattr(self.roster, "batch_name", "") or ""
        name, ok = QInputDialog.getText(self, "重命名批次", "新的批次名称：", text=old)
        if not ok or not name.strip():
            return
        if rename_batch(self.business_name, batch_id, name.strip()):
            self._refresh_batch_combo()

    def _on_delete_batch(self) -> None:
        batch_id = getattr(self.roster, "batch_id", "")
        if not batch_id:
            return
        name = getattr(self.roster, "batch_name", "") or "当前批次"
        ret = QMessageBox.question(
            self, "删除批次",
            f"确定删除批次「{name}」及其中的 {len(self.roster.rows)} 人吗？\n"
            "只删除本机的批量名单，不会删除已经生成的文档。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        if delete_batch(self.business_name, batch_id):
            self._reload_batches()

    # ---------- 表格刷新 ----------

    def _reload_table(self) -> None:
        columns = self.roster.columns or self.template_vars
        dup_keys = self.roster.duplicate_keys()
        self._inline_states = {}

        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        if getattr(self, "_styled_column_count", -1) != len(columns):
            self._styled_column_count = len(columns)
            if len(columns) <= 6:
                self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
                self.table.horizontalHeader().setStretchLastSection(False)
            else:
                self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
                self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setRowCount(len(self.roster.rows))
        for r, row in enumerate(self.roster.rows):
            is_dup = row.key_value(self.roster.key_field) in dup_keys
            for c, name in enumerate(columns):
                item = QTableWidgetItem(str(row.values.get(name, "") or ""))
                bg = self._row_color(row, is_dup, self._required)
                if name in self.formula_fields:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(QColor("#e6f4f1"))
                    item.setToolTip("公式计算字段，改来源值后自动重算，不能直接修改")
                elif name in self.auto_fields:
                    # 自动编号：批量模式下可见（便于核对），但只读避免手改造成账本混乱
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(QColor("#fef3c7"))
                    item.setToolTip(
                        "自动编号字段，生成文档时由账本自动发放。\n"
                        "这里只读展示，避免手改造成编号混乱；要改请用【设置 → 自动编号】。")
                elif bg is not None:
                    item.setBackground(bg)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

        self._update_status_bar()
        self._apply_filter()
        if self._last_sort_column >= 0:
            self.table.horizontalHeader().setSortIndicatorShown(True)
            self.table.horizontalHeader().setSortIndicator(
                self._last_sort_column,
                Qt.DescendingOrder if self._last_sort_desc else Qt.AscendingOrder)

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
        if hasattr(self, "roster_count_label"):
            self.roster_count_label.setText(f"{counts['total']} 人")
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

    def _on_batch_edit_started(self, row: int, _col: int) -> None:
        """批量填充的编辑行：放大 1.5 倍并加浅色底。"""
        if row < 0 or row >= self.table.rowCount():
            return
        self._restore_batch_row(row)
        old_height = self.table.rowHeight(row)
        backgrounds = []
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                backgrounds.append((item, item.background()))
                item.setBackground(QColor("#dbeafe"))
        self._inline_states[row] = (old_height, backgrounds)
        self.table.setRowHeight(row, max(30, int(old_height * 1.5)))

    def _restore_batch_row(self, row: int) -> None:
        state = self._inline_states.pop(row, None)
        if not state:
            return
        old_height, backgrounds = state
        for item, brush in backgrounds:
            try:
                item.setBackground(brush)
            except RuntimeError:
                pass
        if 0 <= row < self.table.rowCount():
            self.table.setRowHeight(row, old_height or 30)

    def _on_batch_edit_finished(self, row: int, _col: int) -> None:
        self._restore_batch_row(row)

    def _batch_cells(self):
        cells = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            for col in range(self.table.columnCount()):
                if self.table.item(row, col) is not None:
                    cells.append((row, col))
        return cells

    def _on_batch_move(self, row: int, col: int, kind: str) -> None:
        """Tab 下一格，回车下一行；跳过隐藏行。"""
        cells = self._batch_cells()
        if not cells:
            return
        current = (row, col)
        if kind == "backtab":
            target = next((cell for cell in reversed(cells) if cell < current), None)
        elif kind == "enter":
            target = next((cell for cell in cells if cell[0] > row and cell[1] == col), None)
        else:
            target = next((cell for cell in cells if cell > current), None)
        if target is None:
            return
        self.table.selectRow(target[0])
        self.table.setCurrentCell(target[0], target[1])
        self.table.scrollToItem(self.table.item(target[0], target[1]))
        self.table.edit(self.table.model().index(target[0], target[1]))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        columns = self.roster.columns or self.template_vars
        if item.column() >= len(columns):
            return
        name = columns[item.column()]
        if name in self.auto_fields:
            self._manual_numbers_by_row.setdefault(item.row(), {})[name] = item.text().strip()
        self.roster.set_value(item.row(), name, item.text())
        self.roster.refresh_status(self._required)
        if not self.roster.save():
            QMessageBox.warning(self, "保存失败", self.roster.load_error or "名单未能保存")
        self._recalc_formula_row(item.row())
        self._update_status_bar()

    def _recalc_formula_row(self, row_index: int) -> None:
        """来源值一改就重算这一行的公式字段，立即显示结果。"""
        if not self.formula_fields or self.resolve_record is None:
            return
        if not 0 <= row_index < len(self.roster.rows):
            return
        columns = self.roster.columns or self.template_vars
        indexes = [c for c, name in enumerate(columns) if name in self.formula_fields]
        if not indexes:
            return
        try:
            record = self.roster.selected_dicts([row_index])[0]
            resolved = self.resolve_record(record) or {}
        except Exception:
            return
        self.table.blockSignals(True)
        for col in indexes:
            name = columns[col]
            item = self.table.item(row_index, col) or QTableWidgetItem()
            item.setText(str(resolved.get(name, "") or ""))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setBackground(QColor("#e6f4f1"))
            item.setToolTip("公式计算字段，改来源值后自动重算，不能直接修改")
            self.table.setItem(row_index, col, item)
            self.roster.set_value(row_index, name, item.text())
        self.table.blockSignals(False)
        self.roster.save()

    def _ask_import_mode(self) -> str:
        """设置为 ask 时让用户本次决定，不写回设置。"""
        dialog = QDialog(self)
        dialog.setStyleSheet(current_style())
        dialog.setWindowTitle("导入方式")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("这批数据要怎么放进当前业务？"))
        options = [
            ("新建批次（推荐）", "new_batch", "旧批次原样保留，互不影响"),
            ("并入当前批次", "merge_current", "按匹配依据补进当前名单，可覆盖冲突"),
            ("取消导入", "cancel", ""),
        ]
        radios = []
        for label, value, desc in options:
            radio = QRadioButton(label + (f"——{desc}" if desc else ""))
            radio.setProperty("mode", value)
            radios.append(radio)
            layout.addWidget(radio)
        radios[0].setChecked(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return "cancel"
        for radio in radios:
            if radio.isChecked():
                return str(radio.property("mode"))
        return "cancel"

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
        if not rows:
            QMessageBox.information(
                self, "没有可导入的数据",
                "文件里只有表头，或只有下载模板自带的示例/说明行。\n请填入真实人员后再导入。")
            return

        dicts = rows_to_dicts(header, rows)
        mode = "new_batch"
        if self.settings is not None:
            mode = str(self.settings.get("batch_import_mode", "new_batch") or "new_batch")
        if mode not in ("new_batch", "merge_current", "ask"):
            mode = "new_batch"
        if mode == "ask":
            mode = self._ask_import_mode()
        if mode == "cancel":
            return

        report_lines = [f"来源：{note}", f"读到 {len(rows)} 行（示例行已自动跳过）"]

        if mode == "new_batch":
            name = os.path.splitext(os.path.basename(path))[0] or "导入批次"
            batch = create_batch(
                self.business_name, name,
                columns=list(self.roster.columns) + list(header),
                key_field=self.roster.key_field,
                incoming=dicts,
            )
            self._reload_batches(batch["id"])
            QMessageBox.information(
                self, "导入完成",
                "\n".join(report_lines + [
                    f"已新建批次「{batch['name']}」，旧批次未改动。",
                    f"本批新增 {len(dicts)} 人。",
                ]))
            return

        result = self.roster.merge_rows(
            dicts, match_field=str(self.key_combo.currentData() or ""),
            overwrite_conflicts=False)
        self.roster.refresh_status(self._required)

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

        report_lines.append(result.summary())
        if removed_cols:
            report_lines.append(f"已删除列：{'、'.join(removed_cols)}")
        if warnings:
            report_lines.append("")
            report_lines.extend(warnings[:5])
        if result.has_issues:
            report_lines.append("")
            report_lines.extend(result.detail_lines())
        QMessageBox.information(self, "导入完成", "\n".join(report_lines))

    def _on_download_template(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存名单模板", default_file_name(self.business_name, "模板"),
            "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            from output.roster_export import template_columns_for_download
            columns, differs = template_columns_for_download(
                self.template_vars, self.roster.columns)
            if differs:
                QMessageBox.information(
                    self, "按业务模板生成",
                    "名单里残留了别的模板的列，已按【当前业务模板的变量】生成空模板。\n"
                    "例如贷款业务就只出现贷款模板里的变量，不会再混入旧列名。")
            write_template_xlsx(path, columns,
                                key_field=self.roster.key_field)
            QMessageBox.information(self, "已导出", f"空模板已保存：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _on_add_row(self) -> None:
        self.roster.add_row()
        self.roster.refresh_status(self._required)
        self.roster.save()
        self._reload_table()

    def _on_open_trash(self) -> None:
        """打开回收站：列出误删的行，可逐条恢复或清空。"""
        trash = getattr(self.roster, "trash", []) or []
        if not trash:
            QMessageBox.information(self, "回收站", "回收站是空的，没有可恢复的行。")
            return
        from PySide6.QtWidgets import QInputDialog
        items = []
        for i, item in enumerate(trash):
            row = item.get("row", {}) or {}
            values = row.get("values", {}) or {}
            name = values.get("姓名") or values.get("客户名") or "（空行）"
            deleted = item.get("deleted_at", "")
            items.append(f"{i}. {name}（删除于 {deleted}）")
        choice, ok = QInputDialog.getItem(
            self, "回收站", "选择要恢复的行：", items, 0, False)
        if not ok:
            return
        trash_index = int(choice.split(".", 1)[0])
        reply = QMessageBox.question(
            self, "恢复", f"恢复「{choice.split('（', 1)[0].split('. ', 1)[-1]}」这一行？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.roster.restore_from_trash(trash_index)
            self.roster.refresh_status(self._required)
            self.roster.save()
            self._reload_table()
            self.status_label.setText("已从回收站恢复 1 行")

    def _on_delete_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要删除的行")
            return
        ret = QMessageBox.question(
            self, "确认删除",
            f"将删除 {len(rows)} 行（进入回收站，之后可恢复）。\n"
            f"不会删除已生成的文档。是否继续？",
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
        """对给定行下标生成文档，更新状态，并按需写入移交清单台账。

        所有结果汇总进一个窗口一屏看全：生成/写入失败、清单追加失败(可重试)、
        成功明细，不再连续弹多个提示窗。
        """
        from core.generate_report import GenerateReport

        if self.on_start:
            # 每次生成前清空上一批的文件清单，避免把上次的多选又打开/打印一遍
            self.on_start()
        records = self.roster.selected_dicts(indexes)
        report = GenerateReport(output_dir=self.output_dir or "", people_count=len(records))
        done_rows: List[int] = []
        dirs: Dict[int, str] = {}
        # 记录每人成功/失败，供台账状态列使用
        result_status: Dict[str, str] = {}
        failed_keys: set = set()

        for row_index, record in zip(indexes, records):
            record["__manual_numbers__"] = dict(
                self._manual_numbers_by_row.get(row_index, {}))
            ok, fail = self.generate_one(record)
            key_value = str(record.get(self.handover_dedup_field, "") or "").strip()
            name = (record.get("姓名") or record.get("客户名") or key_value
                    or f"第{row_index + 1}人")
            if ok:
                report.add_item(str(name), kind="ok")
                self._manual_numbers_by_row.pop(row_index, None)
                done_rows.append(row_index)
                dirs[row_index] = getattr(self, "_last_dir_hint", "")
                # 把本次实际发放的自动编号写回名单行，界面上能直接看到
                for field, value in record.items():
                    if field in self.roster.columns and str(value or "").strip():
                        self.roster.set_value(row_index, field, value)
                if key_value:
                    result_status[key_value] = "已生成"
            else:
                report.add_item(str(name), error=f"{fail} 个模板未成功", kind="generate")
                if key_value:
                    result_status[key_value] = "生成失败"
                failed_keys.add(key_value)

        if done_rows:
            self.roster.mark_generated(done_rows, dirs)
            self.roster.save()
            self._reload_table()

        # 移交清单追加逻辑：抽成闭包，供"重试追加"复用（不再内部循环弹窗）
        def do_append() -> tuple:
            """返回 (note, error, unmatched)。"""
            if not self.handover_enabled or not records:
                return "", "", []
            if not self.output_dir:
                return "", "没有设置输出目录，移交清单无法写入。", []
            from output.handover_ledger import append_batch
            try:
                path, added, updated, unmatched = append_batch(
                    self.output_dir, self.business_name, records,
                    template_path=self.handover_template,
                    dedup_field=self.handover_dedup_field,
                    status_by_key=result_status,
                )
                note = f"移交清单已追加：新增 {added} 人、更新 {updated} 人\n{path}"
                return note, "", list(unmatched or [])
            except Exception as exc:
                return "", str(exc), []

        note, error, unmatched = do_append()
        report.ledger_note, report.ledger_error, report.ledger_unmatched = note, error, unmatched

        if report.success and self.auto_open_output and self.open_output:
            try:
                self.open_output()
            except Exception:
                pass
        self._refresh_number_hint()
        if report.success and self.on_files:
            try:
                self.on_files()
            except Exception:
                pass

        # 单个汇总窗；重试追加在原窗口内就地刷新
        from ui.generate_result_dialog import GenerateResultDialog

        def retry_ledger() -> tuple:
            note2, error2, unmatched2 = do_append()
            if error2:
                return False, error2 + "\n\n常见原因：清单正在 Excel 里打开，关闭后再试。"
            report.ledger_note = note2
            report.ledger_error = ""
            report.ledger_unmatched = unmatched2
            return True, note2

        dialog = GenerateResultDialog(
            report, self, retry_ledger=retry_ledger,
            on_open_output=self.open_output)
        dialog.exec()

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
        act_copy = menu.addAction(f"复制整列（{name}）")
        menu.addSeparator()
        act_fill = menu.addAction(f"批量设值（当前列：{name}）…")
        act_clear = menu.addAction(f"清空整列（{name}）")
        menu.addSeparator()
        act_sort_asc = menu.addAction(f"按「{name}」升序排序")
        act_sort_desc = menu.addAction(f"按「{name}」降序排序")
        chosen = menu.exec(self.table.horizontalHeader().mapToGlobal(pos))
        if chosen == act_copy:
            from ui.table_copy import copy_table
            copy_table(self.table, "column", col=column)
            self.status_label.setText(f"已复制整列：{name}")
        elif chosen == act_fill:
            self._on_bulk_set(preferred_column=name)
        elif chosen == act_clear:
            ret = QMessageBox.question(
                self, "清空整列", f"确定清空「{name}」整列？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.Yes:
                self._fill_column(column, "")
        elif chosen in (act_sort_asc, act_sort_desc):
            self._sort_by_column(name, descending=chosen == act_sort_desc)

    def _on_header_sort_clicked(self, column: int) -> None:
        columns = self.roster.columns or self.template_vars
        if not 0 <= column < len(columns):
            return
        descending = (self._last_sort_column == column and not self._last_sort_desc)
        self._last_sort_column = column
        self._last_sort_desc = descending
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(
            column, Qt.DescendingOrder if descending else Qt.AscendingOrder)
        self._sort_by_column(columns[column], descending=descending)

    def _sort_by_column(self, name: str, descending: bool = False) -> None:
        """按某一列重排名单行，排序后仍能正常编辑/生成（数据行同步重排）。"""
        def key(row):
            text = str(row.values.get(name, "") or "").strip()
            try:
                return (0, float(text.replace(",", "")))
            except ValueError:
                return (1, text.casefold())

        try:
            self.roster.rows.sort(key=key, reverse=descending)
        except Exception as exc:
            QMessageBox.warning(self, "排序失败", str(exc))
            return
        self.roster.save()
        self._reload_table()

    def _on_bulk_set(self, preferred_column: str = "") -> None:
        """批量设值：字段 + 值 + 范围，默认只改选中的行并跳过已生成。"""
        columns = self.roster.columns or self.template_vars
        if not columns:
            return
        selected = sorted({idx.row() for idx in self.table.selectedIndexes()})
        visible = [r for r in range(self.table.rowCount())
                   if not self.table.isRowHidden(r)]
        dialog = BatchSetDialog(
            columns, len(selected), len(visible), len(self.roster.rows),
            preferred_column=preferred_column, parent=self)
        if dialog.exec() != QDialog.Accepted or not dialog.result_data:
            return
        cfg = dialog.result_data
        scope = cfg["scope"]
        if scope == "selected":
            indexes = selected
        elif scope == "visible":
            indexes = visible
        else:
            indexes = list(range(len(self.roster.rows)))
        if not indexes:
            QMessageBox.information(self, "提示", "当前范围内没有可修改的行。")
            return
        column = str(cfg["column"])
        if column in self.formula_fields:
            QMessageBox.information(self, "不能修改", "公式字段由计算得到，请改来源字段。")
            return
        if column in self.auto_fields:
            QMessageBox.information(
                self, "不能修改",
                "「自动编号」字段由账本统一发放，不能批量改。\n"
                "要调整编号规则请到【设置 → 日期与编号】。")
            return
        changed = self.roster.bulk_set(
            indexes, column, str(cfg["value"]),
            skip_generated=bool(cfg["skip_generated"]))
        if changed == 0:
            why = ""
            if cfg["skip_generated"]:
                why = "\n原因：这些行都已生成过文档，而“跳过已生成的行”被勾选了。"
            QMessageBox.information(
                self, "本次没有改动",
                f"本次修改 0 行，名单未变化。{why}\n"
                "如需修改已生成的行，请在批量设值窗口取消“跳过已生成的行”。")
            return
        self.roster.refresh_status(self._required)
        self.roster.save()
        for row_index in indexes:
            self._recalc_formula_row(row_index)
        self._reload_table()
        self.status_label.setText(f"已批量设值：{column}，修改 {changed} 行")

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
        col = self.table.columnAt(pos.x())
        from ui.table_copy import copy_table
        menu = QMenu(self)
        act_copy_row = menu.addAction("复制整行")
        act_copy_col = menu.addAction("复制整列")
        act_copy_cell = menu.addAction("复制当前单元格")
        menu.addSeparator()
        act_dup = menu.addAction("复制为新行")
        chosen = menu.exec(self.table.mapToGlobal(pos))
        if chosen == act_copy_row:
            copy_table(self.table, "row", row=row)
            self.status_label.setText(f"已复制第 {row + 1} 行")
        elif chosen == act_copy_col:
            if col >= 0:
                copy_table(self.table, "column", col=col)
                self.status_label.setText("已复制整列")
        elif chosen == act_copy_cell:
            if col >= 0:
                copy_table(self.table, "cell", row=row, col=col)
                self.status_label.setText("已复制单元格")
        elif chosen == act_dup:
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


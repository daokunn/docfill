"""
主窗口（PySide6 实现）
功能：
  - 顶部工具栏：设置模板根目录、输出根目录、重名策略
  - 左侧：业务列表（点击切换业务，自动扫描模板变量）
  - 右侧：变量表格（双击单元格编辑值、新增/删除自定义变量、CSV导入导出）
  - 操作区：智能粘贴解析、一键生成文档
  - 底部：操作日志输出
模块调用关系：
  scanner -> VariableManager -> renderer -> OutputManager
"""

import os
import sys
import csv
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QTextEdit, QTextBrowser,
    QHeaderView, QComboBox, QLineEdit, QInputDialog, QAbstractItemView,
    QGroupBox, QFormLayout, QDialog, QDialogButtonBox, QCheckBox,
    QProgressDialog, QScrollArea, QFrame,
)
from PySide6.QtGui import QShortcut, QKeySequence, QColor, QIcon, QFont

from app_paths import APP_NAME, APP_VERSION, asset_path, is_subpath
from config.settings import get_settings
from core.scanner import (
    scan_businesses,
    BusinessInfo,
    rename_variables_in_template,
    count_variable_occurrences,
    ordered_variable_names,
)
from core.variable_manager import VariableManager
from core.renderer import render_document, RenderError
from core.preflight import collect_empty_variables
from core.date_format import (
    DATE_FORMAT_PRESETS,
    RANGE_SEPARATOR_PRESETS,
    format_output_values,
    preview_date_format,
)
from core.template_backup import (
    backup_templates,
    clear_last_backup,
    get_last_backup,
    has_last_backup,
    restore_backup,
)
from core.alias_mapper import get_alias_mapper
from core.autonumber import AutoNumberBook
from core.platform_open import open_folder, open_folder_error_hint
from core.user_state import clear_last_data, load_last_data, save_last_data
from output.file_output import OutputManager, OutputError
from ui.smart_paste_dialog import SmartPasteDialog
from ui.style import APP_STYLE, TUTORIAL_HTML
from ui.widgets import VariableTableWidget
from ui.csv_import_dialog import CsvImportDialog


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        """初始化主窗口：加载配置、扫描业务、构建 UI"""
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(980, 640)
        icon_file = asset_path("docfill.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        self.setStyleSheet(APP_STYLE)  # 应用全局现代化浅色主题

        self.settings = get_settings()                     # 全局配置
        self.output_mgr = OutputManager()                   # 输出管理器
        self.businesses: List[BusinessInfo] = []            # 扫描到的业务列表
        self.current_business: Optional[BusinessInfo] = None  # 当前选中的业务
        self.vm: Optional[VariableManager] = None           # 当前业务的变量管理器
        self._last_paste_result: Optional[Dict[str, str]] = None  # 上次智能粘贴结果（数据复用）
        self._last_output_dir: Optional[str] = None         # 上次输出目录（打开目录用）
        self._number_books: Dict[str, AutoNumberBook] = {}   # 每个业务的自动编号账本

        self._build_ui()
        self._restore_window_geometry()
        self._refresh_path_labels()
        self._scan_businesses()
        self._create_shortcuts()

    # ---------- UI 构建 ----------

    def _build_ui(self) -> None:
        """构建主窗口 UI：路径配置区、业务列表、变量表格、操作按钮、日志区"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # 顶部路径配置区
        path_group = QGroupBox("路径配置")
        path_layout = QFormLayout(path_group)
        row1 = QHBoxLayout()
        self.lbl_template = QLabel("(未设置)")
        btn_template = QPushButton("选择模板根目录")
        btn_template.clicked.connect(self._on_set_template)
        row1.addWidget(self.lbl_template, 1)
        row1.addWidget(btn_template)
        path_layout.addRow("模板根目录：", row1)

        row2 = QHBoxLayout()
        self.lbl_output = QLabel("(未设置)")
        btn_output = QPushButton("选择输出根目录")
        btn_output.clicked.connect(self._on_set_output)
        row2.addWidget(self.lbl_output, 1)
        row2.addWidget(btn_output)
        path_layout.addRow("输出根目录：", row2)

        row3 = QHBoxLayout()
        self.cmb_strategy = QComboBox()
        self.cmb_strategy.addItems(["追加序号", "覆盖", "跳过"])
        strategy_map = {"append_seq": 0, "overwrite": 1, "skip": 2}
        self.cmb_strategy.setCurrentIndex(strategy_map.get(self.settings.rename_strategy, 0))
        self.cmb_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        row3.addWidget(self.cmb_strategy)
        row3.addStretch()
        btn_tutorial = QPushButton("使用教程")
        btn_tutorial.clicked.connect(self._on_tutorial)
        row3.addWidget(btn_tutorial)
        self.btn_undo_normalize = QPushButton("撤销上次统一")
        self.btn_undo_normalize.setToolTip("恢复最近一次“统一变量名”修改前的模板")
        self.btn_undo_normalize.setEnabled(has_last_backup())
        self.btn_undo_normalize.clicked.connect(self._on_undo_normalize)
        row3.addWidget(self.btn_undo_normalize)
        btn_settings = QPushButton("设置")
        btn_settings.clicked.connect(self._on_settings)
        row3.addWidget(btn_settings)
        path_layout.addRow("重名策略：", row3)
        main_layout.addWidget(path_group)

        # 主体分割：左业务列表 / 右变量区
        splitter = QSplitter(Qt.Horizontal)

        # 左侧业务列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("业务列表"))
        self.biz_list = QListWidget()
        self.biz_list.currentItemChanged.connect(self._on_business_selected)
        left_layout.addWidget(self.biz_list)
        btn_refresh = QPushButton("刷新业务列表")
        btn_refresh.clicked.connect(self._scan_businesses)
        left_layout.addWidget(btn_refresh)
        splitter.addWidget(left)

        # 右侧变量区
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # 变量表格
        right_layout.addWidget(QLabel("变量列表（单击“值”列即可编辑，支持表达式）"))
        self.var_table = VariableTableWidget(0, 4)
        # 显式设字体：QSS 的 font-size 不作用于单元格编辑器，编辑态会回退到系统小字。
        # 用 QFont 让显示态和编辑态都继承这个稍大的字号，解决"一进编辑就变小"。
        _table_font = QFont()
        _table_font.setPointSizeF(12.5)
        self.var_table.setFont(_table_font)
        self.var_table.verticalHeader().setDefaultSectionSize(30)
        self.var_table.setHorizontalHeaderLabels(["变量名", "值", "必填", "来源"])
        self.var_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # 单击即进入编辑（AllEditTriggers），值列以外的列已在 _refresh_var_table 中设为只读
        self.var_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.var_table.itemChanged.connect(self._on_var_item_changed)
        self.var_table.bulk_paste.connect(self._on_values_pasted)
        right_layout.addWidget(self.var_table)

        self.coverage_label = QLabel("")
        self.coverage_label.setWordWrap(True)
        self.coverage_label.setStyleSheet("color: #6b7280;")
        right_layout.addWidget(self.coverage_label)

        # 变量操作按钮
        var_btns = QHBoxLayout()
        btn_smart = QPushButton("智能粘贴解析")
        btn_smart.setObjectName("primary")  # 蓝色强调样式
        btn_smart.clicked.connect(self._on_smart_paste)
        btn_reuse = QPushButton("应用上次数据")
        btn_reuse.clicked.connect(self._on_reuse_last)
        btn_norm = QPushButton("统一变量名")
        btn_norm.clicked.connect(self._on_normalize_vars)
        btn_add = QPushButton("新增自定义变量")
        btn_add.clicked.connect(self._on_add_var)
        btn_del = QPushButton("删除自定义变量")
        btn_del.clicked.connect(self._on_del_var)
        btn_csv = QPushButton("CSV导入")
        btn_csv.clicked.connect(self._on_csv_import)
        btn_csv_template = QPushButton("单人模板")
        btn_csv_template.setToolTip("导出「变量名,值」竖排 CSV，适合照着右侧变量表填一个人")
        btn_csv_template.clicked.connect(self._on_csv_template)
        btn_roster = QPushButton("人员名单")
        btn_roster.setToolTip("导入一批人（每行一人）、留空待补的字段，之后按姓名搜索继续补录并生成")
        btn_roster.clicked.connect(self._on_open_roster)
        for b in [btn_smart, btn_reuse, btn_norm, btn_add, btn_del, btn_csv, btn_csv_template, btn_roster]:
            var_btns.addWidget(b)
        var_btns.addStretch()
        right_layout.addLayout(var_btns)

        # 生成按钮（绿色大按钮，样式见 style.py #generate）
        gen_row = QHBoxLayout()
        btn_gen = QPushButton("一键生成文档  (Ctrl+G)")
        btn_gen.setObjectName("generate")
        btn_gen.clicked.connect(self._on_generate)
        gen_row.addWidget(btn_gen, 1)
        btn_next = QPushButton("下一单（清空）")
        btn_next.setToolTip("清空当前变量，开始下一位客户")
        btn_next.clicked.connect(self._on_next_case)
        gen_row.addWidget(btn_next)
        right_layout.addLayout(gen_row)

        # 日志区
        right_layout.addWidget(QLabel("操作日志："))
        self.log_text = QTextEdit()
        self.log_text.setObjectName("log")  # 等宽浅灰底样式
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(120)
        right_layout.addWidget(self.log_text)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        motto = QLabel("再快一点点的话，就可以早点下班啦！")
        motto.setStyleSheet("color: #6b7280; font-size: 9pt; padding: 2px 6px;")
        footer.addWidget(motto)
        footer.addStretch()
        self.lbl_next_number = QLabel("")
        self.lbl_next_number.setStyleSheet(
            "color: #2563eb; font-size: 9pt; font-weight: bold; padding: 2px 8px;")
        footer.addWidget(self.lbl_next_number)
        brand = QLabel(f"{APP_NAME} · daokunn")
        brand.setStyleSheet("color: #9ca3af; font-size: 9pt; padding: 2px 6px;")
        footer.addWidget(brand)
        main_layout.addLayout(footer)

    def _restore_window_geometry(self) -> None:
        """恢复上次窗口大小；首次启动按屏幕可用区域自适应。"""
        store = QSettings("DocFill", "DocFill")
        geometry = store.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
            return

        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(1280, max(980, available.width() - 80))
            height = min(820, max(640, available.height() - 100))
            self.resize(width, height)
            self.move(
                available.left() + max(0, (available.width() - width) // 2),
                available.top() + max(0, (available.height() - height) // 2),
            )
        else:
            self.resize(1180, 760)

    def closeEvent(self, event):  # noqa: N802 - Qt 命名
        """退出时保存窗口大小和位置。"""
        QSettings("DocFill", "DocFill").setValue("window/geometry", self.saveGeometry())
        super().closeEvent(event)

    # ---------- 路径配置 ----------

    def _refresh_path_labels(self) -> None:
        """刷新顶部路径显示标签"""
        self.lbl_template.setText(self.settings.template_root_dir or "(未设置)")
        self.lbl_output.setText(self.settings.output_root_dir or "(未设置)")

    def _on_set_template(self) -> None:
        """点击"选择模板根目录"按钮"""
        path = QFileDialog.getExistingDirectory(self, "选择模板根目录")
        if path:
            self.settings.template_root_dir = path
            self._refresh_path_labels()
            self._scan_businesses()
            self._log(f"模板根目录已设置：{path}")

    def _on_set_output(self) -> None:
        """点击"选择输出根目录"按钮（禁止放进模板目录内）"""
        path = QFileDialog.getExistingDirectory(self, "选择输出根目录")
        if not path:
            return

        template_root = self.settings.template_root_dir
        if template_root and is_subpath(path, template_root):
            QMessageBox.critical(
                self, "输出目录不合适",
                "输出目录不能放在模板目录里面，否则生成的文件会和模板混在一起。\n\n"
                f"模板目录：{template_root}\n"
                f"你选择的：{path}\n\n"
                "请选择模板目录之外的文件夹，例如 D:\\生成结果。")
            return

        self.settings.output_root_dir = path
        self._refresh_path_labels()
        self._log(f"输出根目录已设置：{path}")

    def _on_strategy_changed(self, idx: int) -> None:
        """重名策略下拉框变更"""
        strategy = ["append_seq", "overwrite", "skip"][idx]
        self.settings.rename_strategy = strategy
        self._log(f"重名策略已设置：{strategy}")

    # ---------- 业务扫描 ----------

    def _scan_businesses(self) -> None:
        """扫描模板根目录，刷新业务列表"""
        self.biz_list.clear()
        self.businesses = []
        root = self.settings.template_root_dir
        if not root or not os.path.isdir(root):
            self._log("模板根目录未设置或不存在")
            return
        self.businesses = scan_businesses(root)
        for b in self.businesses:
            item = QListWidgetItem(f"{b.name}（{len(b.templates)}模板/{len(b.variables)}变量）")
            item.setData(Qt.UserRole, b.name)
            self.biz_list.addItem(item)
        self._log(f"扫描到 {len(self.businesses)} 项业务")

    def _on_business_selected(self, current: QListWidgetItem, _previous) -> None:
        """业务列表选中项变更：加载该业务的变量"""
        if not current:
            return
        name = current.data(Qt.UserRole)
        for b in self.businesses:
            if b.name == name:
                self.current_business = b
                self._load_variables(b)
                break

    def _load_variables(self, business: BusinessInfo) -> None:
        """根据业务的模板变量初始化 VariableManager 并刷新表格"""
        self.vm = VariableManager(
            business_name=business.name,
            strip_invisible=bool(self.settings.get("strip_invisible_chars", True)),
        )
        order_mode = self.settings.get("variable_order", "template")
        self.vm.init_from_template_vars(
            ordered_variable_names(business, order_mode),
            business.optional_variables,
        )
        self._refresh_var_table()
        self._refresh_number_hint()
        self._log(f"已加载业务 [{business.name}]，共 {len(self.vm.variables)} 个变量")

    def _auto_field_names(self) -> set:
        """当前启用自动编号的变量名集合。"""
        config = self.settings.get("auto_number_fields", {}) or {}
        if not isinstance(config, dict):
            return set()
        return {str(name).strip() for name in config if str(name).strip()}

    def _refresh_var_table(self) -> None:
        """将 VariableManager 中的变量刷新到表格，空变量高亮显示"""
        self.var_table.blockSignals(True)
        self.var_table.setRowCount(0)
        if not self.vm:
            self.var_table.blockSignals(False)
            return
        auto_fields = self._auto_field_names()
        book = self._number_book(self.vm.business_name) if auto_fields else None
        for name, var in self.vm.variables.items():
            row = self.var_table.rowCount()
            self.var_table.insertRow(row)
            # 变量名/必填/来源列设为只读，只有"值"列可编辑（配合 AllEditTriggers 单击编辑）
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 0, name_item)

            is_auto = name in auto_fields and book is not None
            if is_auto:
                # 自动编号变量：直接把下一个号码显示出来并锁定，避免用户手填冲突
                preview = book.peek(name)
                if preview:
                    var.value = preview
            val_item = QTableWidgetItem(str(var.value))
            if is_auto:
                val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)
                val_item.setBackground(QColor("#dbeafe"))
                val_item.setToolTip("自动编号：生成时按序发放，无需手填")
            elif var.value is None or str(var.value).strip() == "":
                # 空变量高亮（柔和浅黄背景）
                val_item.setBackground(QColor("#fef3c7"))
            self.var_table.setItem(row, 1, val_item)
            req_item = QTableWidgetItem("是" if var.required else "否")
            req_item.setFlags(req_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 2, req_item)
            src_item = QTableWidgetItem("自动编号" if is_auto else var.source)
            src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 3, src_item)
        self.var_table.blockSignals(False)
        self._refresh_coverage()

    def _refresh_coverage(self) -> None:
        """显示当前变量表的填写覆盖情况。"""
        if not self.vm:
            self.coverage_label.setText("")
            return
        total = len(self.vm.variables)
        filled = sum(1 for var in self.vm.variables.values() if str(var.value).strip())
        missing = [
            name for name, var in self.vm.variables.items()
            if var.required and not str(var.value).strip() and not var.default_expr
        ]
        optional_empty = [
            name for name, var in self.vm.variables.items()
            if not var.required and not str(var.value).strip()
        ]

        parts = [f"已填写 {filled}/{total}"]
        if missing:
            shown = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
            parts.append(f"待填写必填：{shown}")
        if optional_empty:
            shown = "、".join(optional_empty[:6]) + ("…" if len(optional_empty) > 6 else "")
            parts.append(f"可选为空：{shown}")
        self.coverage_label.setText("；".join(parts))

    def _on_var_item_changed(self, item: QTableWidgetItem) -> None:
        """表格值被编辑时同步到 VariableManager"""
        if not self.vm:
            return
        if item.column() != 1:
            return
        row = item.row()
        name_item = self.var_table.item(row, 0)
        if name_item:
            self.vm.set_value(name_item.text(), item.text())
            self._refresh_coverage()

    def _on_values_pasted(self, text: str, start_row: int) -> None:
        """把 Excel/CSV 剪贴板中的多行/多列内容粘贴到变量表。

        支持两种形式：
        - 单列：从当前行开始，依次填“值”列
        - 两列及以上：第一列是变量名，第二列是值
        """
        if not self.vm:
            return
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return

        rows = [line.split("\t") for line in lines]
        auto_fields = self._auto_field_names()
        by_name = (
            all(len(columns) >= 2 for columns in rows)
            and any(columns[0].strip() in self.vm.variables for columns in rows)
        )

        count = 0
        if by_name:
            for columns in rows:
                name = columns[0].strip()
                if name.lower() in ("变量名", "字段", "字段名", "field", "name"):
                    continue
                if name in auto_fields:
                    continue  # 自动编号变量不接受粘贴，避免和自动递增值冲突
                value = columns[1].strip()
                if name in self.vm.variables:
                    self.vm.set_value(name, value)
                else:
                    self.vm.add_custom_variable(name, value)
                count += 1
        else:
            row_index = max(0, start_row)
            for columns in rows:
                if row_index >= self.var_table.rowCount():
                    break
                name_item = self.var_table.item(row_index, 0)
                if not name_item:
                    break
                if name_item.text() not in auto_fields:
                    self.vm.set_value(name_item.text(), columns[0].strip())
                    count += 1
                row_index += 1

        self._refresh_var_table()
        self._log(f"已从剪贴板批量粘贴 {count} 个变量值")

    def _on_next_case(self) -> None:
        """清空当前变量，开始下一单。"""
        self._clear_current_values(confirm=True)

    def _clear_current_values(self, confirm: bool = True) -> None:
        """清空变量值，保留变量结构和必填标记。"""
        if not self.vm:
            return
        has_values = any(str(var.value).strip() for var in self.vm.variables.values())
        if confirm and has_values:
            ret = QMessageBox.question(
                self, "开始下一单",
                "将清空当前变量表的所有值，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self.vm.clear_values()
        self._last_paste_result = None
        self._refresh_var_table()
        self._log("已清空当前变量，可开始下一单")

    # ---------- 变量操作 ----------

    def _on_normalize_vars(self) -> None:
        """
        统一变量名（由用户自行分组确认）。
        场景：不同时间编写的模板里，同一含义被写成了不同变量名（姓名/客户名/名字/申请人）。
        流程：
          1. 自动应用用户以前确认过的映射（两个名字都在当前模板中出现时），无需再选
          2. 弹出对话框：用户勾选"是同一个意思"的变量，并从中选一个作为统一名
          3. 确认后修改模板文件，映射保存到 aliases.json，下次自动生效
        """
        if not self.current_business:
            QMessageBox.information(self, "提示", "请先选择业务")
            return

        # 1. 收集当前业务所有模板中的变量名
        all_vars = set()
        for tmpl in self.current_business.templates:
            all_vars |= tmpl.variables

        if len(all_vars) < 2:
            QMessageBox.information(self, "提示", "当前业务变量不足 2 个，无需统一")
            return

        mapper = get_alias_mapper()

        # 2. 自动应用已保存的映射（仅当两个名字同时出现在当前业务中，合并才无歧义）
        name_map: Dict[str, str] = {}
        for var_name in sorted(all_vars):
            normalized = mapper.normalize(var_name)
            if normalized != var_name and normalized in all_vars:
                name_map[var_name] = normalized

        # 3. 弹出分组对话框：用户勾选同义变量并选择统一名
        dialog = NormalizeVarsDialog(sorted(all_vars), self)
        if dialog.exec() == QDialog.Accepted and dialog.name_map:
            # 保存用户确认的新映射，下次自动生效
            for old, new in dialog.name_map.items():
                mapper.add_alias(new, old)
            mapper.save()
            name_map.update(dialog.name_map)

        if not name_map:
            self._log("统一变量名：没有需要修改的变量")
            return

        # 4. 预览：统计每个模板将被修改的处数
        affected = []
        total_occurrences = 0
        for tmpl in self.current_business.templates:
            if tmpl.error:
                continue
            count = count_variable_occurrences(tmpl.path, name_map)
            if count:
                affected.append((tmpl, count))
                total_occurrences += count

        if not affected:
            self._log("统一变量名：模板中没有找到需要修改的变量标记")
            QMessageBox.information(self, "提示", "模板中没有找到需要修改的变量标记。")
            return

        mapping_text = "\n".join(f"  {old}  →  {new}" for old, new in sorted(name_map.items()))
        preview_lines = "\n".join(f"  {tmpl.name}：{count} 处" for tmpl, count in affected[:10])
        if len(affected) > 10:
            preview_lines += f"\n  …… 另有 {len(affected) - 10} 个模板"

        ret = QMessageBox.question(
            self, "确认统一变量名",
            f"将对当前业务的模板做以下变量名统一：\n\n{mapping_text}\n\n"
            f"将修改 {len(affected)} 个模板，共 {total_occurrences} 处：\n{preview_lines}\n\n"
            f"修改前会自动备份，完成后可撤销。是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return

        # 5. 先备份，备份失败则绝不修改
        try:
            record = backup_templates([tmpl.path for tmpl, _ in affected])
        except Exception as e:
            self._log(f"[统一变量名] 备份失败：{e}")
            QMessageBox.critical(self, "备份失败", f"模板备份失败，已取消修改：\n{e}")
            return
        self._log(f"[统一变量名] 已备份到：{record.get('backup_dir', '')}")

        # 6. 修改模板文件
        total_changed = 0
        for tmpl, _ in affected:
            try:
                changed = rename_variables_in_template(tmpl.path, name_map)
                total_changed += changed
                if changed > 0:
                    self._log(f"[统一变量名] {tmpl.name}：修改 {changed} 处")
            except Exception as e:
                self._log(f"[统一变量名] {tmpl.name} 失败：{e}")

        # 7. 重新扫描并尽量保持当前业务选中
        current_name = self.current_business.name
        self._refresh_business_after_normalize(current_name)

        self._log(f"统一变量名完成，共修改 {total_changed} 处；备份在 {record.get('backup_dir', '')}")
        self.btn_undo_normalize.setEnabled(True)

        # 8. 完成提示 + 一键撤销
        box = QMessageBox(self)
        box.setWindowTitle("统一变量名完成")
        box.setText(f"共修改 {total_changed} 处。")
        box.setInformativeText(f"修改前已备份到：\n{record.get('backup_dir', '')}")
        btn_undo = box.addButton("撤销本次修改", QMessageBox.DestructiveRole)
        box.addButton("完成", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() == btn_undo:
            self._restore_normalize_backup(record)

    def _refresh_business_after_normalize(self, business_name: str) -> None:
        """重新扫描模板，并尽量选中原来的业务。"""
        self._scan_businesses()
        for i in range(self.biz_list.count()):
            item = self.biz_list.item(i)
            if item.data(Qt.UserRole) == business_name:
                self.biz_list.setCurrentRow(i)
                break

    def _restore_normalize_backup(self, record: Dict) -> None:
        """恢复一次统一变量名修改，并刷新界面。"""
        current_name = self.current_business.name if self.current_business else ""
        restored = restore_backup(record)
        if restored:
            clear_last_backup()
            self._refresh_business_after_normalize(current_name)
            self._log(f"[统一变量名] 已撤销，恢复 {restored} 个模板")
            QMessageBox.information(self, "已撤销", f"已恢复 {restored} 个模板文件。")
        else:
            QMessageBox.warning(self, "撤销失败", "没有找到可恢复的备份文件。")
        self.btn_undo_normalize.setEnabled(has_last_backup())

    def _on_undo_normalize(self) -> None:
        """撤销最近一次统一变量名修改。"""
        record = get_last_backup()
        if not record:
            self.btn_undo_normalize.setEnabled(False)
            QMessageBox.information(self, "提示", "没有可撤销的模板备份。")
            return
        ret = QMessageBox.question(
            self, "撤销上次统一变量名",
            f"将恢复 {len(record.get('files', []))} 个模板文件到修改前的状态。\n\n"
            "当前对模板的修改会被覆盖，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self._restore_normalize_backup(record)

    def _on_smart_paste(self) -> None:
        """打开智能粘贴对话框，解析结果回填到变量管理器"""
        if not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        # 传入变量名->当前值字典，供对话框判断空变量并排序
        var_dict = {name: var.value for name, var in self.vm.variables.items()}
        dialog = SmartPasteDialog(var_dict, self,
                                  business_name=self.current_business.name
                                  if self.current_business else "")
        if not dialog.exec():
            return

        # 多人模式：批量生成文档
        if dialog.multi_results:
            self._batch_generate(dialog.multi_results)
            return

        # 单人模式：回填到变量管理器
        if dialog.result:
            self._last_paste_result = dialog.result  # 缓存供数据复用
            save_last_data(self.current_business.name, self._last_paste_result)
            filled = 0
            for field, value in dialog.result.items():
                if field in self.vm.variables:
                    self.vm.set_value(field, value)
                else:
                    self.vm.add_custom_variable(field, value)
                filled += 1
            self._refresh_var_table()
            self._log(f"智能粘贴回填 {filled} 个变量")

    def _on_reuse_last(self) -> None:
        """应用上次数据：优先内存缓存，其次读取本机持久化记录。"""
        if not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return

        if not self._last_paste_result and self.current_business:
            self._last_paste_result = load_last_data(self.current_business.name) or None

        if not self._last_paste_result:
            QMessageBox.information(self, "提示", "暂无上次数据")
            return

        filled = 0
        for field, value in self._last_paste_result.items():
            if field in self.vm.variables:
                self.vm.set_value(field, value)
                filled += 1
            else:
                self.vm.add_custom_variable(field, value)
                filled += 1
        self._refresh_var_table()
        self._log(f"应用上次数据，回填 {filled} 个变量")

    def _batch_generate(self, people_results: List[Dict[str, str]]) -> None:
        """批量生成多人文档。

        每个人使用独立的 VariableManager，绝不把上一个人的值带进下一个人。
        生成前先检查空变量和“未知客户”，让用户确认后再写文件。
        """
        if not self.current_business:
            return

        prepared = []
        order_mode = self.settings.get("variable_order", "template")
        for i, person_vars in enumerate(people_results, 1):
            person_vm = VariableManager(
                business_name=self.current_business.name,
                strip_invisible=bool(self.settings.get("strip_invisible_chars", True)),
            )
            person_vm.init_from_template_vars(
                ordered_variable_names(self.current_business, order_mode),
                self.current_business.optional_variables,
            )
            for field, value in person_vars.items():
                if field in person_vm.variables:
                    person_vm.set_value(field, value)
                else:
                    person_vm.add_custom_variable(field, value)

            resolved = person_vm.get_output_values()
            name = (
                person_vars.get("姓名")
                or person_vars.get("客户名")
                or f"第{i}人"
            )
            folder = self.output_mgr.build_subfolder_name(self.current_business.name, resolved)
            prepared.append({
                "index": i,
                "name": name,
                "resolved": resolved,
                "folder": folder,
                "missing": collect_empty_variables(self.current_business, resolved),
            })

        missing_people = [p for p in prepared if p["missing"]]
        unknown_people = [p for p in prepared if "未知客户" in p["folder"]]
        if missing_people or unknown_people:
            lines = []
            if unknown_people:
                lines.append("以下人没有识别到客户名/姓名，输出目录会使用“未知客户”：")
                lines.append("、".join(p["name"] for p in unknown_people[:8]))
                lines.append("")
            if missing_people:
                lines.append("以下模板变量为空（未填位置会留空）：")
                for p in missing_people[:8]:
                    lines.append(f"  {p['name']}：{'、'.join(p['missing'][:8])}")
                if len(missing_people) > 8:
                    lines.append(f"  …… 另有 {len(missing_people) - 8} 人")
                lines.append("")

            box = QMessageBox(self)
            box.setWindowTitle("批量生成前检查")
            box.setText(
                f"将生成 {len(prepared)} 人的文档，"
                f"每人 {len([t for t in self.current_business.templates if not t.error])} 个模板。"
            )
            box.setInformativeText("\n".join(lines).strip())
            btn_yes = box.addButton("仍然生成", QMessageBox.AcceptRole)
            btn_no = box.addButton("返回检查", QMessageBox.RejectRole)
            box.setDefaultButton(btn_no)
            box.exec()
            if box.clickedButton() != btn_yes:
                self._log("批量生成已取消：请先补充空变量或确认客户名")
                return

        total_success, total_fail = 0, 0
        for item in prepared:
            self._log(f"\n===== 开始生成第{item['index']}人：{item['name']} =====")
            self._log(f"输出目录：{item['folder']}")
            s, f = self._generate_for_variables(item["resolved"])
            total_success += s
            total_fail += f
            if s:
                save_last_data(
                    self.current_business.name,
                    {name: value for name, value in item["resolved"].items() if str(value).strip()},
                )

        self._log(f"\n批量生成完成：共 {len(prepared)} 人，成功 {total_success} 个，失败 {total_fail} 个")
        self._show_generate_result(total_success, total_fail)

    def _on_add_var(self) -> None:
        """新增自定义变量（非模板变量）"""
        if not self.vm:
            return
        name, ok = QInputDialog.getText(self, "新增自定义变量", "请输入变量名：")
        if ok and name.strip():
            self.vm.add_custom_variable(name.strip())
            self._refresh_var_table()
            self._log(f"新增自定义变量：{name}")

    def _on_del_var(self) -> None:
        """删除选中的自定义变量（模板变量不可删）"""
        if not self.vm:
            return
        row = self.var_table.currentRow()
        if row < 0:
            return
        name = self.var_table.item(row, 0).text()
        var = self.vm.variables.get(name)
        if var and var.source == "custom":
            self.vm.remove_variable(name)
            self._refresh_var_table()
            self._log(f"删除自定义变量：{name}")
        else:
            QMessageBox.information(self, "提示", "模板变量不可删除，仅自定义变量可删除")

    def _on_csv_import(self) -> None:
        """从 CSV 文件批量导入变量值（自动识别 UTF-8 / GBK，先预览）。"""
        if not self.vm:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择CSV文件", "", "CSV文件 (*.csv)")
        if not path:
            return
        try:
            dialog = CsvImportDialog(path, self)
        except Exception as e:
            QMessageBox.critical(self, "CSV 读取失败", str(e))
            return
        if dialog.exec() != QDialog.Accepted:
            return

        count = 0
        skipped_auto = 0
        auto_fields = self._auto_field_names()
        for name, value in dialog.mapping.items():
            if name in auto_fields:
                skipped_auto += 1
                continue  # 自动编号变量由程序发放，导入不覆盖
            if name in self.vm.variables:
                self.vm.set_value(name, value)
            else:
                self.vm.add_custom_variable(name, value)
            count += 1
        self._refresh_var_table()
        note = f"（跳过 {skipped_auto} 个自动编号变量）" if skipped_auto else ""
        self._log(f"CSV 导入成功，共 {count} 个变量{note}（编码：{dialog.encoding}）")

    def _on_csv_template(self) -> None:
        """导出单人竖排 CSV 模板（配合右侧变量表一格一格填）。"""
        if not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存单人填写模板", "变量模板.csv", "CSV文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["变量名", "值"])
                for name in self.vm.variables:
                    writer.writerow([name, ""])
            self._log(f"已导出单人模板：{path}")
            QMessageBox.information(
                self, "已导出",
                f"单人填写模板已保存：\n{path}\n\n"
                "如果要一批人（每行一个人），请用【人员名单】窗口里的「下载空模板」。")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # ---------- 人员名单 ----------

    # ---------- 自动编号 ----------

    def _number_book(self, business_name: str) -> AutoNumberBook:
        """取某个业务的编号账本（每次从磁盘读，避免设置窗口改号后缓存过期）。"""
        book = AutoNumberBook(business_name)
        self._number_books[business_name] = book
        config = self.settings.get("auto_number_fields", {}) or {}
        if isinstance(config, dict):
            for field, seed in config.items():
                book.configure(str(field), str(seed or ""))
        return book

    def _assign_auto_numbers(self, values: Dict[str, str], business_name: str) -> Dict[str, str]:
        """给一条待生成数据发放编号；返回各字段原来的 last，供失败回退。"""
        config = self.settings.get("auto_number_fields", {}) or {}
        if not isinstance(config, dict) or not config:
            return {}
        book = self._number_book(business_name)
        previous: Dict[str, str] = {}
        for field in config:
            field = str(field or "").strip()
            if not field:
                continue
            previous[field] = str((book.data.get(field) or {}).get("last") or "")
            number = book.consume(field)
            if number:
                values[field] = number
        return previous

    def _rollback_auto_numbers(self, business_name: str, previous: Dict[str, str]) -> None:
        if not previous:
            return
        book = self._number_book(business_name)
        for field, last in previous.items():
            book.rollback(field, last)

    def _number_hint_text(self) -> str:
        """当前各自动编号字段的下一个号码文本。"""
        if not self.current_business:
            return ""
        config = self.settings.get("auto_number_fields", {}) or {}
        if not isinstance(config, dict) or not config:
            return ""
        book = self._number_book(self.current_business.name)
        parts = []
        for field in config:
            field = str(field or "").strip()
            if not field:
                continue
            nxt = book.peek(field)
            if nxt:
                parts.append(f"{field} {nxt}")
        return ("下个编号：" + "；".join(parts)) if parts else ""

    def _refresh_number_hint(self) -> None:
        """左下角显示当前各自动编号字段的下一个号码。"""
        if not hasattr(self, "lbl_next_number"):
            return
        self.lbl_next_number.setText(self._number_hint_text())

    def _on_open_roster(self) -> None:
        """打开独立的人员名单窗口（导入宽表、留空待补、按姓名搜索续填、生成选中）。"""
        if not self.current_business:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        if not self.settings.output_root_dir:
            QMessageBox.information(self, "提示", "请先设置输出根目录")
            return

        from ui.roster_window import RosterWindow

        business = self.current_business
        template_vars = ordered_variable_names(business, self.settings.get("variable_order", "template"))
        optional_vars = list(business.optional_variables)
        batch_items: List[Dict[str, str]] = []

        def generate_one(record: Dict[str, str]) -> Tuple[int, int]:
            # 名单生成期间临时把当前业务对齐，复用现有渲染流程
            self.current_business = business
            # 真实生成时才发放档案号：没有文档就不会占号，避免断号
            number_previous = self._assign_auto_numbers(record, business.name)
            resolved = format_output_values(
                dict(record),
                date_format=self.settings.get("date_format"),
                range_separator=self.settings.get("date_range_separator"),
            )
            ok, fail = self._generate_for_variables(resolved)
            if not ok and fail:
                self._rollback_auto_numbers(business.name, number_previous)
            batch_items.extend(getattr(self, "_last_generated_items", []))
            self._refresh_number_hint()
            return ok, fail

        window = RosterWindow(
            business_name=business.name,
            template_vars=template_vars,
            optional_vars=optional_vars,
            generate_one=generate_one,
            open_output=self._open_last_output,
            auto_open_output=bool(self.settings.get("open_folder_after_generate", True)),
            output_dir=self.settings.output_root_dir,
            handover_enabled=bool(self.settings.get("handover_enabled", True)),
            handover_template=str(self.settings.get("handover_template", "") or ""),
            handover_dedup_field=str(self.settings.get("handover_dedup_field", "姓名") or "姓名"),
            number_hint=self._number_hint_text,
            on_files=lambda: self._after_generate_files(batch_items),
            parent=self,
        )
        self._roster_window = window  # 防止被回收
        window.show()
        window.raise_()
        window.activateWindow()

    # ---------- 生成文档 ----------

    def _on_generate(self) -> None:
        """一键生成文档：预检 -> 解析变量 -> 渲染模板 -> 输出到业务子文件夹"""
        if not self.current_business or not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        if not self.settings.output_root_dir:
            QMessageBox.information(self, "提示", "请先设置输出根目录")
            return

        resolved = self.vm.get_output_values()
        number_previous = self._assign_auto_numbers(resolved, self.current_business.name)
        missing = collect_empty_variables(self.current_business, resolved)
        folder_name = self.output_mgr.build_subfolder_name(self.current_business.name, resolved)
        unknown_customer = "未知客户" in folder_name
        template_count = len([t for t in self.current_business.templates if not t.error])

        if missing or unknown_customer:
            lines = [
                f"输出目录：{folder_name}",
                f"模板：{template_count} 个",
                "",
            ]
            if unknown_customer:
                lines.append("没有识别到客户名/姓名，目录会使用“未知客户”。建议先填写客户名或姓名。")
                lines.append("")
            if missing:
                lines.append("以下模板变量为空（未填位置会留空）：")
                lines.append("、".join(missing[:12]) + (" 等" if len(missing) > 12 else ""))
                lines.append("")

            box = QMessageBox(self)
            box.setWindowTitle("生成前检查")
            box.setText("即将生成文档，请确认以下信息。")
            box.setInformativeText("\n".join(lines).strip())
            btn_yes = box.addButton("仍然生成", QMessageBox.AcceptRole)
            btn_no = box.addButton("返回修改", QMessageBox.RejectRole)
            box.setDefaultButton(btn_no)
            box.exec()
            if box.clickedButton() != btn_yes:
                self._rollback_auto_numbers(self.current_business.name, number_previous)
                self._refresh_number_hint()
                self._refresh_var_table()
                self._log("生成已取消：请先补充空变量或确认客户名")
                return

        self._log(f"\n准备生成：{folder_name}（{template_count} 个模板）")
        success, fail = self._generate_for_variables(resolved)
        if not success and fail:
            # 全部失败：退回号码，避免占用造成断号
            self._rollback_auto_numbers(self.current_business.name, number_previous)
        self._refresh_number_hint()
        self._refresh_var_table()
        if success:
            self._after_generate_files(list(getattr(self, "_last_generated_items", [])))
        if success:
            save_last_data(
                self.current_business.name,
                {name: var.value for name, var in self.vm.variables.items() if str(var.value).strip()},
            )
        self._log(f"\n生成完成：成功 {success} 个，失败 {fail} 个")
        self._show_generate_result(success, fail)

    def _show_generate_result(self, success: int, fail: int) -> None:
        """显示生成结果，提供打开输出目录/下一单按钮。

        用自定义对话框而不是 QMessageBox：QMessageBox 的按钮行在中文长标签下
        容易被截断，这里显式布局保证三个按钮完整可见。
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("生成完成")
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)

        title = QLabel(f"生成完成：成功 {success} 个，失败 {fail} 个")
        title.setStyleSheet("font-size: 12pt; font-weight: bold; color: #1f2937;")
        layout.addWidget(title)

        if self._last_output_dir:
            dir_label = QLabel("输出目录：")
            dir_label.setStyleSheet("color: #6b7280;")
            layout.addWidget(dir_label)
            path_label = QLabel(self._last_output_dir)
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_label.setWordWrap(True)
            path_label.setStyleSheet(
                "background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px 8px;"
            )
            layout.addWidget(path_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_open = QPushButton("打开输出目录")
        btn_open.setObjectName("primary")
        btn_open.clicked.connect(lambda: (dialog.accept(), self._open_last_output()))
        btn_next = QPushButton("下一单（清空）")
        btn_next.clicked.connect(lambda: (dialog.accept(), self._clear_current_values(confirm=True)))
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.reject)
        for b in (btn_open, btn_next, btn_close):
            b.setMinimumWidth(120)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        # 生成成功且开了自动打开：先弹出资源管理器，再显示结果框（结果框仍可手动开/下一单）
        if success and self.settings.get("open_folder_after_generate", True):
            self._open_last_output()

        accepted = dialog.exec() == QDialog.Accepted
        if not accepted and self.settings.get("clear_after_generate", False) and success:
            self._clear_current_values(confirm=False)

    def _after_generate_files(self, items: List[Dict[str, str]]) -> None:
        """按设置打开/打印本次生成的文件（只在自动打开输出文件夹开启时生效）。

        :param items: [{"path": 输出文件, "template": 模板相对路径, "name": 模板名}]
        """
        if not items:
            return
        if not self.settings.get("open_folder_after_generate", True):
            return
        if not self.settings.get("open_generated_files", False):
            return

        from core.open_print import open_files, print_files

        mode = str(self.settings.get("open_files_mode", "all") or "all")
        selected = {str(v) for v in (self.settings.get("open_files_templates", []) or [])}
        if mode == "first":
            items = items[:1]
        elif mode == "specified":
            if selected:
                items = [item for item in items
                         if item.get("template") in selected or item.get("name") in selected]
            else:
                # 兼容旧配置：没有选模板时按文件名匹配
                spec = str(self.settings.get("open_files_specified", "") or "").strip()
                if not spec:
                    self._log("[打开] 已设为只打开指定模板，但还没有勾选模板")
                    return
                name = os.path.basename(spec)
                items = [item for item in items
                         if os.path.basename(item.get("path", "")) == name]
            if not items:
                self._log("[打开] 本次生成结果里没有勾选模板对应的文件")
                return

        # 去重，避免同一文件打开/打印两次
        seen = set()
        targets: List[str] = []
        for item in items:
            path = item.get("path", "")
            if path and path not in seen:
                seen.add(path)
                targets.append(path)
        if not targets:
            return

        opened, failed = open_files(targets)
        self._log(f"[打开] 已打开 {opened} 个文件" + (f"，{failed} 个失败" if failed else ""))
        if self.settings.get("auto_print_after_open", False):
            printed, print_failed = print_files(
                targets,
                copies=int(self.settings.get("print_copies", 1) or 1),
                printer=str(self.settings.get("printer_name", "") or ""),
            )
            self._log(f"[打印] 已发送 {printed} 个文件到默认打印机"
                      + (f"，{print_failed} 个失败" if print_failed else ""))

    def _open_last_output(self) -> None:
        """打开最近一次输出目录（Windows / 麒麟等 Linux 桌面通用）。"""
        if not self._last_output_dir:
            return
        # 不用 os.startfile：它是 Windows 独有的，在 Linux 上抛 AttributeError，
        # 而 AttributeError 不是 OSError 的子类，原来的 except 接不住会直接崩。
        if not open_folder(self._last_output_dir):
            QMessageBox.warning(
                self, "无法打开目录",
                open_folder_error_hint(self._last_output_dir))

    def _generate_for_variables(self, resolved: Dict[str, str]) -> Tuple[int, int]:
        """
        根据解析后的变量字典生成当前业务的所有文档。
        :return: (成功数, 失败数)
        """
        self._last_generated_files = []
        self._last_generated_items: List[Dict[str, str]] = []
        try:
            output_dir = self.output_mgr.get_output_dir(self.current_business.name, resolved)
            self._last_output_dir = output_dir  # 记录供打开目录
        except OutputError as e:
            QMessageBox.critical(self, "输出错误", str(e))
            return 0, 0

        logger = self.output_mgr.get_logger(output_dir)
        logger.info(f"===== 开始生成业务：{self.current_business.name} =====")

        templates = self.current_business.templates
        progress = None
        if len(templates) >= 4:
            progress = QProgressDialog("正在生成文档...", "取消", 0, len(templates), self)
            progress.setWindowTitle("正在生成")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(300)
            progress.setValue(0)

        success, fail = 0, 0
        cancelled = False
        for index, tmpl in enumerate(templates):
            if progress and progress.wasCanceled():
                cancelled = True
                logger.warning("用户取消生成，剩余模板未处理")
                break
            if progress:
                progress.setLabelText(f"正在生成：{tmpl.name}")
                progress.setValue(index)
                QApplication.processEvents()

            if tmpl.error:
                self._log(f"[跳过] {tmpl.name}：{tmpl.error}")
                logger.warning(f"跳过模板 {tmpl.name}：{tmpl.error}")
                fail += 1
                continue
            out_path = self.output_mgr.resolve_output_path(tmpl.rel_path, output_dir, resolved)
            if not out_path:
                self._log(f"[跳过] {tmpl.name}：文件已存在")
                logger.info(f"跳过（已存在）：{tmpl.name}")
                continue
            try:
                layout_log: List[str] = []
                render_document(
                    tmpl.path,
                    out_path,
                    resolved,
                    shrink_overflow_font=bool(self.settings.get("shrink_overflow_font", True)),
                    layout_log=layout_log,
                )
                self._log(f"[成功] {tmpl.name} -> {os.path.basename(out_path)}")
                for msg in layout_log:
                    self._log(f"  [版式] {msg}")
                    logger.info(f"版式调整：{msg}")
                logger.info(f"生成成功：{tmpl.name} -> {out_path}")
                self._last_generated_files.append(out_path)
                self._last_generated_items.append({
                    "path": out_path,
                    "template": str(tmpl.rel_path or ""),
                    "name": str(tmpl.name or ""),
                })
                success += 1
            except RenderError as e:
                self._log(f"[失败] {tmpl.name}：{e}")
                logger.error(f"生成失败 {tmpl.name}：{e}")
                fail += 1

        if progress:
            progress.setValue(len(templates))
            progress.close()
        if cancelled:
            self._log("已取消生成，已完成的部分文件保留在输出目录")

        logger.info(f"===== 生成完成：成功 {success}，失败 {fail} =====")
        self.output_mgr.reset_logger()
        self._log(f"输出目录：{output_dir}")
        return success, fail

    # ---------- 日志 ----------

    def _log(self, msg: str) -> None:
        """向底部日志区追加一条消息"""
        self.log_text.append(msg)

    # ---------- 快捷键 ----------

    def _create_shortcuts(self) -> None:
        """根据 settings 中的配置创建快捷键"""
        sc = self.settings.get("shortcuts", {})
        self._shortcuts = []
        action_map = {
            "smart_paste": self._on_smart_paste,
            "generate": self._on_generate,
            "rescan": self._scan_businesses,
            "reuse": self._on_reuse_last,
        }
        for key, action in action_map.items():
            seq = sc.get(key, "")
            if seq:
                shortcut = QShortcut(QKeySequence(seq), self)
                shortcut.activated.connect(action)
                self._shortcuts.append(shortcut)

    def _on_settings(self) -> None:
        """打开设置对话框（排序、日期格式、输出命名、快捷键）"""
        variable_names = []
        if self.current_business:
            variable_names = ordered_variable_names(
                self.current_business,
                self.settings.get("variable_order", "template"),
            )
        old_order = self.settings.get("variable_order", "template")
        old_strip = bool(self.settings.get("strip_invisible_chars", True))
        values_before = {}
        if self.vm:
            values_before = {
                name: (var.value, var.source)
                for name, var in self.vm.variables.items()
            }

        dialog = SettingsDialog(
            self.settings,
            self,
            variable_names=variable_names,
            business_name=self.current_business.name if self.current_business else "",
            template_names=(
                [{"name": t.name, "rel_path": t.rel_path}
                 for t in self.current_business.templates]
                if self.current_business else []
            ),
        )
        if dialog.exec() == QDialog.Accepted:
            # 重新创建快捷键
            for sc in getattr(self, "_shortcuts", []):
                sc.setEnabled(False)
            self._create_shortcuts()

            if dialog.cleared_last_data:
                self._last_paste_result = None

            # 排序或不可见字符开关变了：保留当前值，重建变量表让新设置立即生效
            new_strip = bool(self.settings.get("strip_invisible_chars", True))
            if self.current_business and (
                self.settings.get("variable_order", "template") != old_order
                or new_strip != old_strip
            ):
                business = self.current_business
                self._load_variables(business)
                if self.vm:
                    for name, (value, source) in values_before.items():
                        if name in self.vm.variables:
                            self.vm.set_value(name, value)
                        elif source == "custom":
                            self.vm.add_custom_variable(name, value)
                    self._refresh_var_table()

            # 自动编号配置可能变了：重建账本并刷新下个号码显示
            self._number_books.clear()
            self._refresh_number_hint()
            self._refresh_var_table()
            self._log("设置已更新")

    def _on_tutorial(self) -> None:
        """打开使用教程弹窗（内容见 ui/style.py TUTORIAL_HTML）"""
        TutorialDialog(self).exec()


class TutorialDialog(QDialog):
    """使用教程弹窗：富文本展示操作步骤与常见问题"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用教程 · 3 步上手")
        self.resize(820, 700)
        icon_file = asset_path("docfill.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet("QTextBrowser { background: #ffffff; border: 1px solid #e5e7eb; }")
        browser.document().setDocumentMargin(18)
        browser.setHtml(TUTORIAL_HTML)
        layout.addWidget(browser, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText("我知道了")
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


class SettingsDialog(QDialog):
    """设置对话框：输出命名、日期格式、快捷键。"""

    SHORTCUT_LABELS = {
        "smart_paste": "智能粘贴解析",
        "generate": "一键生成文档",
        "rescan": "重新扫描模板",
        "reuse": "应用上次数据",
    }

    def __init__(self, settings, parent=None, variable_names=None, business_name=None,
                 template_names=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(620, 780)
        self.settings = settings
        self.variable_names = list(variable_names or [])
        self.template_names = list(template_names or [])
        self.business_name = business_name or ""
        self.cleared_last_data = False
        self._shortcut_inputs = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        # 设置项越来越多，放进滚动区，小屏幕也能完整操作
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # 输出命名
        layout.addWidget(QLabel("<b>输出命名</b>"))
        layout.addWidget(QLabel("客户名变量（用于“业务_客户名_年月”文件夹命名）："))
        self.customer_combo = QComboBox()
        self.customer_combo.addItem("自动（客户名 → 姓名 → 单位）", "")
        for name in self.variable_names:
            self.customer_combo.addItem(name, name)
        current_customer = str(self.settings.get("customer_var", "") or "")
        index = self.customer_combo.findData(current_customer)
        if index < 0:
            if current_customer:
                self.customer_combo.addItem(f"{current_customer}（当前设置）", current_customer)
            index = 0
        self.customer_combo.setCurrentIndex(index)
        layout.addWidget(self.customer_combo)

        layout.addWidget(QLabel("变量表排序："))
        self.order_combo = QComboBox()
        self.order_combo.addItem("填写顺序（模板出现顺序，推荐）", "template")
        self.order_combo.addItem("字典顺序（按名称排序）", "alphabetical")
        order_index = self.order_combo.findData(self.settings.get("variable_order", "template"))
        self.order_combo.setCurrentIndex(max(order_index, 0))
        layout.addWidget(self.order_combo)

        layout.addWidget(QLabel("身份证号变量（重名文件追加后四位）："))
        self.id_card_combo = QComboBox()
        self.id_card_combo.addItem("自动（身份证号）", "")
        for name in self.variable_names:
            self.id_card_combo.addItem(name, name)
        current_id = str(self.settings.get("id_card_var", "身份证号") or "")
        id_index = self.id_card_combo.findData(current_id)
        if id_index < 0:
            if current_id:
                self.id_card_combo.addItem(f"{current_id}（当前设置）", current_id)
            id_index = 0
        self.id_card_combo.setCurrentIndex(id_index)
        layout.addWidget(self.id_card_combo)

        # 日期格式
        layout.addWidget(QLabel("<b>日期格式</b>"))
        form = QFormLayout()
        self.date_combo = QComboBox()
        self.date_combo.setEditable(True)
        self.date_combo.addItems(DATE_FORMAT_PRESETS)
        self.date_combo.setCurrentText(
            str(self.settings.get("date_format", DATE_FORMAT_PRESETS[0]) or DATE_FORMAT_PRESETS[0])
        )
        form.addRow("日期格式：", self.date_combo)

        self.range_combo = QComboBox()
        self.range_combo.setEditable(True)
        self.range_combo.addItems(RANGE_SEPARATOR_PRESETS)
        self.range_combo.setCurrentText(
            str(self.settings.get("date_range_separator", RANGE_SEPARATOR_PRESETS[0]) or RANGE_SEPARATOR_PRESETS[0])
        )
        form.addRow("起止连接词：", self.range_combo)
        layout.addLayout(form)

        hint = QLabel("支持：YYYY、YY、MM、M、DD、D；例如 YYYY年M月D日 → 2026年1月1日")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280;")
        layout.addWidget(hint)

        self.date_preview = QLabel("")
        self.date_preview.setWordWrap(True)
        self.date_preview.setStyleSheet("color: #2563eb; font-weight: bold;")
        layout.addWidget(self.date_preview)
        self.date_combo.currentTextChanged.connect(self._update_date_preview)
        self.range_combo.currentTextChanged.connect(self._update_date_preview)
        self._update_date_preview()

        self.clear_checkbox = QCheckBox("生成成功后自动清空变量表，开始下一单")
        self.clear_checkbox.setChecked(bool(self.settings.get("clear_after_generate", False)))
        layout.addWidget(self.clear_checkbox)

        self.open_folder_checkbox = QCheckBox("生成成功后自动打开输出文件夹")
        self.open_folder_checkbox.setChecked(
            bool(self.settings.get("open_folder_after_generate", True))
        )
        layout.addWidget(self.open_folder_checkbox)

        self.open_print_config = {
            "open_generated_files": bool(self.settings.get("open_generated_files", False)),
            "open_files_mode": str(self.settings.get("open_files_mode", "all") or "all"),
            "open_files_templates": list(self.settings.get("open_files_templates", []) or []),
            "open_files_specified": str(self.settings.get("open_files_specified", "") or ""),
            "auto_print_after_open": bool(self.settings.get("auto_print_after_open", False)),
            "silent_print": bool(self.settings.get("silent_print", True)),
            "printer_name": str(self.settings.get("printer_name", "") or ""),
            "print_copies": int(self.settings.get("print_copies", 1) or 1),
        }
        open_print_row = QHBoxLayout()
        self.btn_open_print = QPushButton("打开与打印…")
        self.btn_open_print.clicked.connect(self._on_configure_open_print)
        open_print_row.addWidget(self.btn_open_print)
        self.open_print_summary = QLabel("")
        self.open_print_summary.setWordWrap(True)
        self.open_print_summary.setStyleSheet("color:#374151;")
        open_print_row.addWidget(self.open_print_summary, 1)
        layout.addLayout(open_print_row)
        self._refresh_open_print_summary()

        # 移交清单台账
        layout.addWidget(QLabel("<b>移交清单（汇总台账）</b>"))
        self.handover_checkbox = QCheckBox("启用：每批人员生成后自动追加进一张 Excel 移交清单")
        self.handover_checkbox.setChecked(bool(self.settings.get("handover_enabled", True)))
        layout.addWidget(self.handover_checkbox)

        template_row = QHBoxLayout()
        self.handover_template_edit = QLineEdit(str(self.settings.get("handover_template", "") or ""))
        self.handover_template_edit.setPlaceholderText("留空=自动生成标准表头；可指定你们的《移交表》.xlsx")
        btn_pick = QPushButton("选择模板…")
        btn_pick.clicked.connect(self._on_pick_handover_template)
        template_row.addWidget(QLabel("汇总模板："))
        template_row.addWidget(self.handover_template_edit, 1)
        template_row.addWidget(btn_pick)
        layout.addLayout(template_row)

        dedup_row = QHBoxLayout()
        self.handover_dedup_combo = QComboBox()
        for name in (self.variable_names or []):
            self.handover_dedup_combo.addItem(name, name)
        current_dedup = str(self.settings.get("handover_dedup_field", "姓名") or "姓名")
        if self.handover_dedup_combo.findData(current_dedup) < 0:
            self.handover_dedup_combo.addItem(current_dedup, current_dedup)
        self.handover_dedup_combo.setCurrentIndex(max(self.handover_dedup_combo.findData(current_dedup), 0))
        dedup_row.addWidget(QLabel("去重依据列："))
        dedup_row.addWidget(self.handover_dedup_combo, 1)
        dedup_hint = QLabel("同一人重复移交时按此列匹配旧行更新，不重复加行")
        dedup_hint.setStyleSheet("color:#6b7280; font-size:9pt;")
        dedup_row.addWidget(dedup_hint)
        layout.addLayout(dedup_row)

        # 自动编号（档案号/管理序号）：可多选，每个变量一行起始号
        layout.addWidget(QLabel("<b>自动编号（档案号 / 管理序号）</b>"))
        number_hint = QLabel(
            "勾选需要自动生成的变量并填「起始号」。之后每生成一份真实文档才 +1；"
            "没有文档不会占号，因此不会断号。格式随意，程序只把最后一段数字加 1。")
        number_hint.setWordWrap(True)
        number_hint.setStyleSheet("color:#6b7280; font-size:9pt;")
        layout.addWidget(number_hint)

        configured = self.settings.get("auto_number_fields", {}) or {}
        if not isinstance(configured, dict):
            configured = {}
        self.auto_number_fields = dict(configured)

        auto_row = QHBoxLayout()
        self.btn_auto_number = QPushButton("配置自动编号…")
        self.btn_auto_number.clicked.connect(self._on_configure_auto_numbers)
        auto_row.addWidget(self.btn_auto_number)
        self.auto_number_summary = QLabel("")
        self.auto_number_summary.setWordWrap(True)
        self.auto_number_summary.setStyleSheet("color:#374151;")
        auto_row.addWidget(self.auto_number_summary, 1)
        layout.addLayout(auto_row)
        self._refresh_auto_number_summary()

        self.shrink_checkbox = QCheckBox("内容超出格子时自动缩小字号（保住页数；关闭则绝不改格式）")
        self.shrink_checkbox.setChecked(bool(self.settings.get("shrink_overflow_font", True)))
        self.shrink_checkbox.setToolTip(
            "版式保护是默认行为：只替换文字、不动任何格式。\n"
            "唯一例外：当真实数据比占位符长、格子里必然多占行时，\n"
            "允许把该单元格的字号适度调小以避免表格被撑到下一页。\n"
            "最多缩到原字号的 70%，再长就不缩了（宁可溢出也不出蚂蚁字）。"
        )
        layout.addWidget(self.shrink_checkbox)

        self.strip_invisible_checkbox = QCheckBox("自动去除不可见字符（零宽空格、BOM、不换行空格等）")
        self.strip_invisible_checkbox.setChecked(
            bool(self.settings.get("strip_invisible_chars", True))
        )
        self.strip_invisible_checkbox.setToolTip(
            "从网页/微信/Excel 复制的资料常带肉眼看不见的字符，\n"
            "会导致身份证校验失败、地址匹配不上等问题。\n"
            "开启后，手动输入和粘贴的值都会自动清理这些隐藏字符。"
        )
        layout.addWidget(self.strip_invisible_checkbox)

        # 快捷键
        layout.addWidget(QLabel("<b>快捷键</b>"))
        layout.addWidget(QLabel("格式如 Ctrl+G、F5、Ctrl+Shift+V；留空则禁用。"))
        sc = self.settings.get("shortcuts", {})
        shortcut_form = QFormLayout()
        for key, label in self.SHORTCUT_LABELS.items():
            edit = QLineEdit(sc.get(key, ""))
            edit.setPlaceholderText("留空则禁用")
            self._shortcut_inputs[key] = edit
            shortcut_form.addRow(f"{label}：", edit)
        layout.addLayout(shortcut_form)

        layout.addWidget(QLabel("<b>本机缓存</b>"))
        btn_clear_cache = QPushButton("清除本业务上次数据")
        btn_clear_cache.clicked.connect(self._clear_cached_data)
        layout.addWidget(btn_clear_cache)

        about = QLabel(
            f'{APP_NAME} {APP_VERSION} · 作者/联系：daokunn · '
            '<a href="https://github.com/daokunn/docfill">github.com/daokunn/docfill</a>'
        )
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        about.setStyleSheet("color: #6b7280; font-size: 9pt;")
        layout.addWidget(about)

        layout.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _refresh_open_print_summary(self) -> None:
        """设置界面里显示打开/打印配置摘要。"""
        if not hasattr(self, "open_print_summary"):
            return
        cfg = self.open_print_config
        if not cfg.get("open_generated_files"):
            self.open_print_summary.setText("生成后打开文件：未启用")
            return
        mode = cfg.get("open_files_mode")
        mode_text = {"all": "全部文件", "first": "第一个文件",
                     "specified": "指定模板"}.get(mode, "全部文件")
        text = f"生成后打开：{mode_text}"
        if mode == "specified":
            chosen = cfg.get("open_files_templates") or []
            text += f"（{len(chosen)} 个模板）" if chosen else "（未选模板）"
        if cfg.get("auto_print_after_open"):
            text += "；打开后自动打印"
            text += f" {cfg.get('print_copies', 1)} 份"
            if cfg.get("silent_print"):
                text += "（静默）"
        self.open_print_summary.setText(text)

    def _on_configure_open_print(self) -> None:
        """打开独立的打开/打印配置窗口。"""
        from ui.open_print_dialog import OpenPrintDialog

        dialog = OpenPrintDialog(self.open_print_config,
                                 templates=self.template_names, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.open_print_config = dict(dialog.result_config)
            self._refresh_open_print_summary()

    def _refresh_auto_number_summary(self) -> None:
        """在设置界面显示当前启用的自动编号变量。"""
        if not hasattr(self, "auto_number_summary"):
            return
        if not self.auto_number_fields:
            self.auto_number_summary.setText("未启用")
            return
        parts = [f"{name}（{seed or '未填起始号'}）"
                 for name, seed in self.auto_number_fields.items()]
        self.auto_number_summary.setText("已启用：" + "、".join(parts))

    def _on_configure_auto_numbers(self) -> None:
        """打开独立的大窗口配置自动编号。"""
        from ui.autonumber_dialog import AutoNumberDialog

        dialog = AutoNumberDialog(
            self.variable_names or [],
            self.auto_number_fields,
            business_name=self.business_name,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.auto_number_fields = dict(dialog.fields)
            self._refresh_auto_number_summary()

    def _on_pick_handover_template(self) -> None:
        """选择作为移交清单表头来源的 Excel 模板。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择汇总模板（第一行为表头）", "", "Excel 文件 (*.xlsx *.xlsm)")
        if path:
            self.handover_template_edit.setText(path)

    def _clear_cached_data(self) -> None:
        """清除当前业务上次保存的数据。"""
        if not self.business_name:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        ret = QMessageBox.question(
            self, "清除上次数据",
            f"将清除业务「{self.business_name}」保存在本机的上次数据，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        clear_last_data(self.business_name)
        self.cleared_last_data = True
        QMessageBox.information(self, "已清除", "本机上次数据已清除。")

    def _update_date_preview(self) -> None:
        """实时预览日期格式和起止连接词。"""
        self.date_preview.setText(
            "预览：" + preview_date_format(
                self.date_combo.currentText(),
                self.range_combo.currentText(),
            )
        )

    def _on_accept(self) -> None:
        """保存快捷键、日期格式和输出命名设置。"""
        date_format = self.date_combo.currentText().strip()
        range_separator = self.range_combo.currentText().strip()
        if not date_format:
            QMessageBox.warning(self, "格式不完整", "日期格式不能为空。")
            return
        if "Y" not in date_format or "D" not in date_format:
            QMessageBox.warning(
                self, "格式不完整",
                "日期格式至少需要包含年份（Y）和日期（D），例如 YYYY年M月D日。")
            return

        shortcuts = {}
        for key, edit in self._shortcut_inputs.items():
            val = edit.text().strip()
            if val:
                shortcuts[key] = val

        self.settings.set("date_format", date_format)
        self.settings.set("date_range_separator", range_separator or "至")
        self.settings.set("customer_var", self.customer_combo.currentData() or "")
        self.settings.set("variable_order", self.order_combo.currentData() or "template")
        self.settings.set("id_card_var", self.id_card_combo.currentData() or "身份证号")
        self.settings.set("clear_after_generate", self.clear_checkbox.isChecked())
        self.settings.set("open_folder_after_generate", self.open_folder_checkbox.isChecked())
        for key, value in self.open_print_config.items():
            self.settings.set(key, value)
        self.settings.set("handover_enabled", self.handover_checkbox.isChecked())
        self.settings.set("handover_template", self.handover_template_edit.text().strip())
        self.settings.set("handover_dedup_field", self.handover_dedup_combo.currentData() or "姓名")
        # 自动编号：保存独立窗口里配置的变量及起始号
        self.settings.set("auto_number_fields", dict(self.auto_number_fields))
        self.settings.set("shrink_overflow_font", self.shrink_checkbox.isChecked())
        self.settings.set("strip_invisible_chars", self.strip_invisible_checkbox.isChecked())
        self.settings.set("shortcuts", shortcuts)
        self.accept()


class NormalizeVarsDialog(QDialog):
    """
    统一变量名对话框：
    用户从扫描到的变量中勾选"是同一个意思"的一组，再从中选一个作为统一名。
    确认后产出 name_map = {其他变量名: 统一名}，由调用方修改模板并保存映射。
    """

    def __init__(self, var_names: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("统一变量名")
        self.resize(420, 480)
        self.name_map: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "勾选“是同一个意思”的变量名，再选择其中一个作为统一名。\n"
            "确认后，所有模板里的其他名字都会改成统一名，且以后自动生效。\n"
            "（有多组时，确定一组后可再次点击本功能继续）"))

        # 变量勾选列表
        self.var_list = QListWidget()
        for name in var_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.var_list.addItem(item)
        self.var_list.itemChanged.connect(lambda *_: self._refresh_combo())
        layout.addWidget(self.var_list, 1)

        # 统一名下拉框（只列出已勾选项）
        row = QHBoxLayout()
        row.addWidget(QLabel("统一为："))
        self.combo = QComboBox()
        row.addWidget(self.combo, 1)
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _checked_names(self) -> List[str]:
        """返回所有被勾选的变量名"""
        names = []
        for i in range(self.var_list.count()):
            item = self.var_list.item(i)
            if item.checkState() == Qt.Checked:
                names.append(item.text())
        return names

    def _refresh_combo(self) -> None:
        """勾选变化时刷新"统一为"下拉框，保持当前选择不丢"""
        names = self._checked_names()
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if current in names:
            self.combo.setCurrentText(current)
        self.combo.blockSignals(False)

    def _on_accept(self) -> None:
        """校验勾选并生成 name_map"""
        checked = self._checked_names()
        target = self.combo.currentText()
        if len(checked) < 2:
            QMessageBox.information(self, "提示", "请至少勾选 2 个变量名")
            return
        if not target:
            QMessageBox.information(self, "提示", "请选择统一后的变量名")
            return
        self.name_map = {n: target for n in checked if n != target}
        self.accept()

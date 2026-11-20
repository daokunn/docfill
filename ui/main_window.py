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
import stat
import sys
import csv
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QTextEdit, QTextBrowser,
    QHeaderView, QComboBox, QLineEdit, QInputDialog, QAbstractItemView,
    QGroupBox, QFormLayout, QDialog, QDialogButtonBox, QCheckBox,
    QProgressDialog, QScrollArea, QFrame, QSizePolicy, QTabWidget,
)
from PySide6.QtGui import QShortcut, QKeySequence, QColor, QIcon, QFont

from app_paths import APP_DIR, APP_NAME, APP_VERSION, asset_path, is_subpath
from config.settings import DEFAULT_SETTINGS, get_settings
from core.scanner import (
    scan_businesses,
    BusinessInfo,
    rename_variables_in_template,
    count_variable_occurrences,
    ordered_variable_names,
)
from core.variable_manager import VariableManager
from core.variable_groups import group_of
from core.renderer import render_document, RenderError
from core.preflight import collect_empty_variables
from core.date_format import (
    DATE_FORMAT_PRESETS,
    RANGE_SEPARATOR_PRESETS,
    format_output_values,
    is_date_field,
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
from core.autonumber import AutoNumberBook, resolve_manual
from core.platform_open import open_folder, open_folder_error_hint
from core.user_state import clear_last_data, load_last_data, save_last_data
from core.history_store import append_history, clear_history
from ui.history_dialog import HistoryDialog
from ui.widgets import VariableTableWidget, InlineEditDelegate
from output.file_output import OutputManager, OutputError
from ui.smart_paste_dialog import SmartPasteDialog
from ui.style import APP_STYLE, TUTORIAL_HTML, build_style, current_style, current_theme, current_tutorial_html
from ui.csv_import_dialog import CsvImportDialog


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        """初始化主窗口：加载配置、扫描业务、构建 UI"""
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(1080, 700)
        icon_file = asset_path("docfill.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        self.setStyleSheet(current_style())  # 应用当前主题（可在设置里切换）

        self.settings = get_settings()                     # 全局配置
        # 旧版本默认“模板顺序”，升级后一次性切到智能分组；用户仍可在设置改回
        if not self.settings.get("order_migrated", False):
            if self.settings.get("variable_order", "smart") == "template":
                self.settings.set("variable_order", "smart")
            self.settings.set("order_migrated", True)
        self.output_mgr = OutputManager()                   # 输出管理器
        self.businesses: List[BusinessInfo] = []            # 扫描到的业务列表
        self.current_business: Optional[BusinessInfo] = None  # 当前选中的业务
        self.vm: Optional[VariableManager] = None           # 当前业务的变量管理器
        self._last_paste_result: Optional[Dict[str, str]] = None  # 上次智能粘贴结果（数据复用）
        self._last_output_dir: Optional[str] = None         # 上次输出目录（打开目录用）
        self._number_books: Dict[str, AutoNumberBook] = {}   # 每个业务的自动编号账本
        self._locked_numbers: Dict[str, str] = {}            # 历史数据沿用的原编号
        self._locked_business = ""
        self._generated_auto_numbers: Dict[str, str] = {}    # 本次生成实际发放的编号
        self._generated_auto_business = ""
        self._manual_numbers: Dict[str, str] = {}             # 单人模式手工改的编号
        self._roster_window = None                            # 批量窗口（复用，避免多开不同步）

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

        # 顶部路径卡片：模板 / 输出 + 目录与辅助入口
        top_card = QFrame()
        top_card.setObjectName("topCard")
        path_bar = QHBoxLayout(top_card)
        path_bar.setContentsMargins(12, 8, 12, 8)
        path_bar.setSpacing(10)
        caption_t = QLabel("模板")
        caption_t.setObjectName("caption")
        path_bar.addWidget(caption_t)
        self.lbl_template = QLabel("(未设置)")
        self.lbl_template.setObjectName("pathValue")
        self.lbl_template.setMinimumWidth(120)
        self.lbl_template.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_bar.addWidget(self.lbl_template, 2)
        caption_o = QLabel("输出")
        caption_o.setObjectName("caption")
        path_bar.addWidget(caption_o)
        self.lbl_output = QLabel("(未设置)")
        self.lbl_output.setObjectName("pathValue")
        self.lbl_output.setMinimumWidth(100)
        self.lbl_output.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_bar.addWidget(self.lbl_output, 1)
        btn_dir = QPushButton("目录设置…")
        btn_dir.setObjectName("ghost")
        btn_dir.setToolTip("一次设置模板目录、输出目录和重名策略")
        btn_dir.clicked.connect(self._on_directory_settings)
        path_bar.addWidget(btn_dir)
        btn_tutorial = QPushButton("教程")
        btn_tutorial.setObjectName("ghost")
        btn_tutorial.setToolTip("查看三步上手教程")
        btn_tutorial.clicked.connect(self._on_tutorial)
        path_bar.addWidget(btn_tutorial)
        btn_settings = QPushButton("设置")
        btn_settings.setObjectName("ghost")
        btn_settings.setToolTip("日期格式、自动编号、打印、备份等全局设置")
        btn_settings.clicked.connect(self._on_settings)
        path_bar.addWidget(btn_settings)
        main_layout.addWidget(top_card)

        # 主体分割：左业务列表 / 右变量区
        splitter = QSplitter(Qt.Horizontal)

        # 左侧业务列表（卡片）
        left = QFrame()
        left.setObjectName("sideCard")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        biz_header = QHBoxLayout()
        biz_title = QLabel("业务列表")
        biz_title.setObjectName("sectionTitle")
        biz_header.addWidget(biz_title)
        biz_header.addStretch()
        self.biz_count_label = QLabel("0")
        self.biz_count_label.setObjectName("bizCount")
        biz_header.addWidget(self.biz_count_label)
        left_layout.addLayout(biz_header)
        self.biz_search = QLineEdit()
        self.biz_search.setObjectName("searchBox")
        self.biz_search.setPlaceholderText("搜索业务…")
        self.biz_search.setClearButtonEnabled(True)
        self.biz_search.textChanged.connect(self._filter_businesses)
        left_layout.addWidget(self.biz_search)
        self.biz_list = QListWidget()
        self.biz_list.setObjectName("bizList")
        self.biz_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.biz_list.setTextElideMode(Qt.ElideRight)
        self.biz_list.currentItemChanged.connect(self._on_business_selected)
        left_layout.addWidget(self.biz_list, 1)
        btn_refresh = QPushButton("刷新业务列表")
        btn_refresh.setObjectName("ghost")
        btn_refresh.setToolTip("模板有增删改时，重新扫描模板目录")
        btn_refresh.clicked.connect(self._scan_businesses)
        left_layout.addWidget(btn_refresh)
        self.btn_undo_normalize = QPushButton("撤销上次统一")
        self.btn_undo_normalize.setObjectName("ghost")
        self.btn_undo_normalize.setToolTip("恢复最近一次“统一变量名”修改前的模板")
        self.btn_undo_normalize.setEnabled(has_last_backup())
        self.btn_undo_normalize.clicked.connect(self._on_undo_normalize)
        left_layout.addWidget(self.btn_undo_normalize)
        splitter.addWidget(left)

        # 右侧变量区
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # 变量表格
        var_header = QHBoxLayout()
        var_title = QLabel("变量填写")
        var_title.setObjectName("sectionTitle")
        var_header.addWidget(var_title)
        var_step = QLabel("① 选业务   ② 填数据   ③ 生成")
        var_step.setObjectName("sectionHint")
        var_header.addWidget(var_step)
        var_header.addStretch()
        right_layout.addLayout(var_header)
        var_hint = QLabel("单击“值”列编辑，编辑行放大高亮；右键可复制整行/整列")
        var_hint.setObjectName("sectionHint")
        right_layout.addWidget(var_hint)
        self.var_table = VariableTableWidget(0, 5)
        # 显式设字体：QSS 的 font-size 不作用于单元格编辑器，编辑态会回退到系统小字。
        # 用 QFont 让显示态和编辑态都继承这个稍大的字号，解决"一进编辑就变小"。
        _table_font = QFont()
        _table_font.setPointSizeF(12.5)
        self.var_table.setFont(_table_font)
        self.var_table.verticalHeader().setDefaultSectionSize(30)
        self.var_table.setHorizontalHeaderLabels(["变量名", "值", "必填", "来源", "分组"])
        # 所有列都允许用户拖拽调整宽度；默认宽度在下面设置，值列随窗口自适应
        self.var_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.var_table.horizontalHeader().setStretchLastSection(False)
        self.var_table.horizontalHeader().setSortIndicatorShown(False)
        self.var_table.horizontalHeader().sectionClicked.connect(self._on_var_header_sort)
        self.var_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.var_table.horizontalHeader().customContextMenuRequested.connect(
            self._on_var_header_menu)
        self._var_sort_col = -1
        self._var_sort_desc = False
        for index, width in ((0, 160), (1, 360), (2, 58), (3, 70), (4, 90)):
            self.var_table.setColumnWidth(index, width)
        # 原地编辑：编辑时整行放大并高亮
        self.var_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.var_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.var_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._inline_delegate = InlineEditDelegate(self.var_table)
        self.var_table.setItemDelegate(self._inline_delegate)
        self._inline_delegate.editStarted.connect(self._on_inline_edit_started)
        self._inline_delegate.editFinished.connect(self._on_inline_edit_finished)
        self._inline_delegate.moveRequested.connect(self._on_inline_move)
        self._inline_states = {}
        self.var_table.itemChanged.connect(self._on_var_item_changed)
        self.var_table.bulk_paste.connect(self._on_values_pasted)
        self.var_table.row_dropped.connect(self._on_variable_row_dropped)
        # 拖拽之外的可靠兜底：右键上移/下移
        self.var_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.var_table.customContextMenuRequested.connect(self._on_var_table_menu)
        right_layout.addWidget(self.var_table, 1)

        history_row = QHBoxLayout()
        self.history_banner = QLabel("")
        self.history_banner.setStyleSheet("color:#0f766e; font-weight:bold;")
        self.history_banner.hide()
        history_row.addWidget(self.history_banner, 1)
        self.btn_new_number = QPushButton("改用新编号")
        self.btn_new_number.setToolTip("不再沿用历史档案号，下次生成按当前顺序发新号")
        self.btn_new_number.clicked.connect(self._release_locked_numbers)
        self.btn_new_number.hide()
        history_row.addWidget(self.btn_new_number)
        right_layout.addLayout(history_row)

        self.coverage_label = QLabel("")
        self.coverage_label.setObjectName("coveragePill")
        self.coverage_label.setWordWrap(True)
        right_layout.addWidget(self.coverage_label)

        # 常用操作（第一行，字少一点，小白也能看懂）
        var_btns = QHBoxLayout()
        btn_smart = QPushButton("粘贴识别")
        btn_smart.setObjectName("primary")  # 蓝色强调样式
        btn_smart.setToolTip("把客户资料整段粘贴进来，自动识别姓名、证件号、电话等")
        btn_smart.clicked.connect(self._on_smart_paste)
        btn_rules = QPushButton("默认值 / 公式…")
        btn_rules.setToolTip("设置变量默认值，或写 A=B+C、身份证号[6:14] 这类公式；也可新增辅助变量")
        btn_rules.clicked.connect(self._on_variable_rules)
        btn_roster = QPushButton("批量填充")
        btn_roster.setToolTip("导入一批人（每行一人），批量补录并生成；适合资料分批到的情况")
        btn_roster.clicked.connect(self._on_open_roster)
        btn_reuse = QPushButton("上次数据")
        btn_reuse.setToolTip("把上一位客户填过的数据带过来，少打一遍")
        btn_reuse.clicked.connect(self._on_reuse_last)
        for b in (btn_smart, btn_rules, btn_roster, btn_reuse):
            b.setMinimumHeight(34)
            var_btns.addWidget(b)
        var_btns.addStretch()
        right_layout.addLayout(var_btns)

        # 辅助工具（第二行，放不常用的，避免第一行太挤）
        more_btns = QHBoxLayout()
        btn_csv = QPushButton("CSV 导入")
        btn_csv.setToolTip("从 CSV 文件批量导入变量值")
        btn_csv.clicked.connect(self._on_csv_import)
        btn_csv_template = QPushButton("单人模板")
        btn_csv_template.setToolTip("导出「变量名,值」竖排 CSV，适合照着右侧变量表填一个人")
        btn_csv_template.clicked.connect(self._on_csv_template)
        btn_norm = QPushButton("统一名称")
        btn_norm.setToolTip("把模板里不同叫法的变量合并成一个名字")
        btn_norm.clicked.connect(self._on_normalize_vars)
        btn_add = QPushButton("新增变量")
        btn_add.setToolTip("模板里没有、但这次要额外填写的变量")
        btn_add.clicked.connect(self._on_add_var)
        btn_del = QPushButton("删除变量")
        btn_del.setToolTip("只删除你自己新增的变量，模板变量不能删")
        btn_del.clicked.connect(self._on_del_var)
        for b in (btn_csv, btn_csv_template, btn_norm, btn_add, btn_del):
            b.setMinimumHeight(28)
            more_btns.addWidget(b)
        more_btns.addStretch()
        right_layout.addLayout(more_btns)

        # 生成按钮（绿色大按钮，样式见 style.py #generate）
        gen_row = QHBoxLayout()
        btn_gen = QPushButton("一键生成文档  (Ctrl+G)")
        btn_gen.setObjectName("generate")
        btn_gen.setToolTip("按当前变量生成这个业务下的全部 Word / Excel 文档")
        btn_gen.clicked.connect(self._on_generate)
        gen_row.addWidget(btn_gen, 1)
        right_actions = QVBoxLayout()
        right_actions.setSpacing(4)
        btn_history = QPushButton("历史数据…")
        btn_history.setToolTip("从当前业务的历史数据里选一条，填回来修改后重新生成")
        btn_history.clicked.connect(self._on_history)
        right_actions.addWidget(btn_history)
        btn_next = QPushButton("下一单（清空）")
        btn_next.setToolTip("清空当前变量，开始下一位客户")
        btn_next.clicked.connect(self._on_next_case)
        right_actions.addWidget(btn_next)
        gen_row.addLayout(right_actions)
        action_card = QFrame()
        action_card.setObjectName("actionCard")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(10, 10, 10, 10)
        action_layout.addLayout(gen_row)
        right_layout.addWidget(action_card)

        # 日志区默认收起，把高度让给变量表；需要排查时点右下角【日志】
        self.log_text = QTextEdit()
        self.log_text.setObjectName("log")  # 等宽浅灰底样式
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(80)
        self.log_text.hide()
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
            "color: #0f766e; font-size: 9pt; font-weight: bold; padding: 2px 8px;")
        footer.addWidget(self.lbl_next_number)
        self.btn_fix_number = QPushButton("改编号…")
        self.btn_fix_number.setToolTip(
            "直接修改下一次要用的档案号/序号；输出错了不用进设置慢慢找")
        self.btn_fix_number.clicked.connect(self._on_fix_number)
        self.btn_fix_number.hide()
        footer.addWidget(self.btn_fix_number)
        self.btn_log = QPushButton("日志")
        self.btn_log.setObjectName("ghost")
        self.btn_log.setCheckable(True)
        self.btn_log.setToolTip("展开/收起操作日志；平时收起，把空间留给变量表")
        self.btn_log.toggled.connect(self._toggle_log)
        footer.addWidget(self.btn_log)
        brand = QLabel(f"{APP_NAME} · daokunn")
        brand.setStyleSheet("color: #9ca3af; font-size: 9pt; padding: 2px 6px;")
        footer.addWidget(brand)
        main_layout.addLayout(footer)
        QTimer.singleShot(0, self._fit_var_columns)

    def _fit_var_columns(self) -> None:
        """把值列撑满剩余宽度，其他列可由用户拖动调整。"""
        if not hasattr(self, "var_table"):
            return
        viewport = self.var_table.viewport().width()
        if viewport <= 0:
            return
        fixed = sum(
            self.var_table.columnWidth(i) for i in range(self.var_table.columnCount())
            if i != 1 and not self.var_table.isColumnHidden(i)
        )
        self.var_table.setColumnWidth(1, max(180, viewport - fixed - 2))

    def resizeEvent(self, event):  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        if hasattr(self, "var_table"):
            self._fit_var_columns()

    def _toggle_log(self, checked: bool) -> None:
        """展开/收起日志。"""
        self.log_text.setVisible(checked)
        self.btn_log.setText("收起日志" if checked else "日志")

    def _restore_window_geometry(self) -> None:
        """恢复上次窗口大小；首次启动按屏幕可用区域自适应。"""
        store = QSettings("DocFill", "DocFill")
        geometry = store.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
            screen = QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                target_w = max(1080, min(1480, available.width() - 50))
                target_h = max(700, min(940, available.height() - 30))
                # 只把过小的旧窗口拉大，不覆盖用户主动调过的尺寸
                if self.width() < 1080 or self.height() < 760:
                    self.resize(
                        min(max(self.width(), target_w), available.width()),
                        min(max(self.height(), target_h), available.height()))
            elif self.width() < 1080 or self.height() < 700:
                self.resize(max(self.width(), 1080), max(self.height(), 700))
            return

        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = max(1080, min(1480, available.width() - 50))
            height = max(700, min(940, available.height() - 30))
            self.resize(width, height)
            self.move(
                available.left() + max(0, (available.width() - width) // 2),
                available.top() + max(0, (available.height() - height) // 2),
            )
        else:
            self.resize(1180, 800)

    def closeEvent(self, event):  # noqa: N802 - Qt 命名
        """退出时保存窗口大小和位置。"""
        QSettings("DocFill", "DocFill").setValue("window/geometry", self.saveGeometry())
        super().closeEvent(event)

    # ---------- 路径配置 ----------

    def _refresh_path_labels(self) -> None:
        """刷新顶部路径显示标签（长路径省略，悬停看完整路径）。"""
        template = self.settings.template_root_dir or "(未设置)"
        output = self.settings.output_root_dir or "(未设置)"
        self.lbl_template.setText(template)
        self.lbl_output.setText(output)
        self.lbl_template.setToolTip(template)
        self.lbl_output.setToolTip(output)
        # 路径再长也不把「目录设置」按钮挤出窗口
        self.lbl_template.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def _on_directory_settings(self) -> None:
        """一个窗口设置模板目录、输出目录和重名策略。"""
        from ui.directory_dialog import DirectoryDialog

        business_name = self.current_business.name if self.current_business else ""
        profile = self.settings.business_directory(business_name) if business_name else {}
        template_default = (profile.get("template") or [""])[0] or self.settings.template_root_dir
        output_default = (profile.get("output") or [""])[0] or self.settings.output_root_dir
        dialog = DirectoryDialog(
            template_default,
            output_default,
            self.settings.rename_strategy,
            self,
            business_name=business_name,
            recent_templates=(
                [self.settings.template_root_dir]
                + self.settings.recent_directories("template", business_name)),
            recent_outputs=(
                [self.settings.output_root_dir]
                + self.settings.recent_directories("output", business_name)),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        template, output, strategy = dialog.values()
        if template and output and is_subpath(output, template):
            QMessageBox.critical(
                self, "输出目录不合适",
                "输出目录不能放在模板目录里面，否则生成的文件会和模板混在一起。\n\n"
                f"模板目录：{template}\n你选择的输出：{output}\n\n"
                "请选择模板目录之外的文件夹，例如 D:\\生成结果。")
            return
        old_template = self.settings.template_root_dir
        self.settings.template_root_dir = template
        self.settings.output_root_dir = output
        self.settings.rename_strategy = strategy
        if business_name:
            self.settings.remember_business_directory(business_name, template, output)
        self._refresh_path_labels()
        if template != old_template:
            self._scan_businesses()
        self._log(f"目录已更新：模板 {template or '(未设置)'}；输出 {output or '(未设置)'}")

    def _on_set_template(self) -> None:
        """兼容旧按钮：选择模板根目录。"""
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
            self.biz_count_label.setText("0")
            self._log("模板根目录未设置或不存在")
            return
        self.businesses = scan_businesses(root)
        # 最近用过的业务排前面，业务多时不用每次从头找
        from core.scanner import sort_businesses_by_recency
        self.businesses = sort_businesses_by_recency(
            self.businesses, self.settings.get("recent_businesses", []))
        for b in self.businesses:
            item = QListWidgetItem(f"{b.name}（{len(b.templates)}模板/{len(b.variables)}变量）")
            item.setData(Qt.UserRole, b.name)
            item.setToolTip(f"{b.name}\n模板 {len(b.templates)} 个，变量 {len(b.variables)} 个")
            self.biz_list.addItem(item)
            # 有模板解析失败时明确提示，避免"变量少了一个"却不知道原因
            for tmpl in b.templates:
                if tmpl.error:
                    self._log(f"[模板无法解析] {b.name}/{tmpl.name}：{tmpl.error}")
        self.biz_count_label.setText(str(len(self.businesses)))
        self._filter_businesses(self.biz_search.text())
        # 模板重扫后，已打开的名单窗口也要跟上新的列/必填集合
        old_window = getattr(self, "_roster_window", None)
        if (old_window is not None and old_window.isVisible()
                and self.current_business is not None):
            try:
                old_window.refresh_template(
                    self._ordered_names(self.current_business),
                    list(self.current_business.optional_variables))
            except Exception:
                pass
        self._log(f"扫描到 {len(self.businesses)} 项业务")

    def _filter_businesses(self, keyword: str) -> None:
        """按关键字过滤左侧业务列表。"""
        keyword = str(keyword or "").strip().casefold()
        for row in range(self.biz_list.count()):
            item = self.biz_list.item(row)
            item.setHidden(bool(keyword and keyword not in item.text().casefold()))

    def _on_business_selected(self, current: QListWidgetItem, _previous) -> None:
        """业务列表选中项变更：加载该业务的变量"""
        if not current:
            return
        name = current.data(Qt.UserRole)
        # 记录最近使用：下次打开该业务排在最前
        if name:
            from core.scanner import touch_recent_business
            self.settings.set("recent_businesses",
                touch_recent_business(self.settings.get("recent_businesses", []), name))
        for b in self.businesses:
            if b.name == name:
                self.current_business = b
                self._manual_numbers = {}
                self._restore_business_output(b)
                self._load_variables(b)
                break

    def _ordered_names(self, business: BusinessInfo, mode: Optional[str] = None) -> List[str]:
        """统一的变量排序入口：支持 template / smart / alphabetical / custom。"""
        mode = mode or str(self.settings.get("variable_order", "smart") or "smart")
        saved = (self.settings.get("custom_variable_order", {}) or {}).get(business.name, [])
        if mode != "custom":
            return ordered_variable_names(business, mode)
        if not isinstance(saved, list) or not saved:
            # 还没为这个业务拖过顺序，先用智能分组兜底
            return ordered_variable_names(business, "smart")
        base = ordered_variable_names(business, "smart")
        ordered = [str(name) for name in saved if str(name) in base]
        seen = set(ordered)
        for name in base:
            if name not in seen:
                ordered.append(name)
        return ordered

    def _restore_business_output(self, business: BusinessInfo) -> None:
        """切换业务时自动回到该业务上次用的输出目录。"""
        profile = self.settings.business_directory(business.name)
        output = (profile.get("output") or [""])[0]
        if output and output != self.settings.output_root_dir:
            self.settings.output_root_dir = output
            self._refresh_path_labels()
            self._log(f"已切换到业务上次的输出目录：{output}")

    def _load_variables(self, business: BusinessInfo) -> None:
        """根据业务的模板变量初始化 VariableManager 并刷新表格"""
        if self._locked_business and self._locked_business != business.name:
            self._set_history_numbers("", {})
        if self._generated_auto_business and self._generated_auto_business != business.name:
            self._reset_generated_auto()
        self.vm = VariableManager(
            business_name=business.name,
            strip_invisible=bool(self.settings.get("strip_invisible_chars", True)),
        )
        self.vm.init_from_template_vars(
            self._ordered_names(business),
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
        self._inline_states = {}
        if not self.vm:
            self.var_table.blockSignals(False)
            return
        auto_fields = self._auto_field_names()
        book = self._number_book(self.vm.business_name) if auto_fields else None
        resolved = self.vm.get_all_resolved()
        self._last_resolved = resolved
        for name, var in self.vm.variables.items():
            row = self.var_table.rowCount()
            self.var_table.insertRow(row)
            # 变量名/必填/来源列设为只读，只有"值"列可编辑（配合 AllEditTriggers 单击编辑）
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 0, name_item)

            is_auto = name in auto_fields and book is not None
            is_formula = var.rule_mode == "formula"
            is_default = var.rule_mode == "default" or bool(var.default_expr)
            is_aux = var.kind == "aux"
            shown = resolved.get(name, var.value)
            if is_formula or is_aux:
                shown = resolved.get(name, "")
            elif is_default and not str(var.value or "").strip():
                shown = resolved.get(name, "")
            if is_auto:
                # 本次已生成：显示真正写进文档的编号；否则显示历史/下一个号
                preview = ""
                generated = ""
                if self._generated_auto_business == self.vm.business_name:
                    generated = self._generated_auto_numbers.get(name, "")
                if generated:
                    preview = generated
                elif self._locked_business == self.vm.business_name:
                    preview = self._locked_numbers.get(name, "")
                if name in self._manual_numbers:
                    preview = self._manual_numbers[name]
                elif not preview:
                    preview = book.peek(name)
                if preview:
                    var.value = preview
                shown = preview or shown
            val_item = QTableWidgetItem("" if shown is None else str(shown))
            if is_auto:
                val_item.setBackground(QColor("#dbeafe"))
                mode_text = ("仅本次生效" if self.settings.get("number_manual_mode", "once") == "once"
                             else "同时改账本下一号")
                val_item.setToolTip(
                    f"自动编号，可直接修改（{mode_text}）；留空则自动生成")
            elif is_formula or is_aux:
                val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)
                val_item.setBackground(QColor("#ecfeff" if is_aux else "#e0f2fe"))
                if var.rule_error:
                    val_item.setToolTip(f"公式计算失败：{var.rule_error}")
                    val_item.setBackground(QColor("#fee2e2"))
                else:
                    val_item.setToolTip("自动计算，不需要手填")
            elif is_default and not str(var.value or "").strip():
                val_item.setBackground(QColor("#f3f4f6"))
                font = val_item.font()
                font.setItalic(True)
                val_item.setFont(font)
                val_item.setToolTip("默认值：可直接修改覆盖")
            elif var.value is None or str(var.value).strip() == "":
                # 空变量高亮（柔和浅黄背景）
                val_item.setBackground(QColor("#fef3c7"))
            self.var_table.setItem(row, 1, val_item)
            if is_aux:
                req_text = "—"
            else:
                req_text = "是" if var.required else "否"
            req_item = QTableWidgetItem(req_text)
            req_item.setFlags(req_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 2, req_item)
            if is_auto:
                if (self._generated_auto_business == self.vm.business_name
                        and self._generated_auto_numbers.get(name)):
                    src_text = "已生成"
                elif (self._locked_business == self.vm.business_name
                      and self._locked_numbers.get(name)):
                    src_text = "历史编号"
                else:
                    src_text = "自动编号"
            elif is_formula:
                src_text = "计算"
            elif is_default:
                src_text = "默认值"
            elif is_aux:
                src_text = "辅助"
            else:
                src_text = var.source
            src_item = QTableWidgetItem(src_text)
            src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 3, src_item)

            group = "辅助变量" if is_aux else group_of(name)
            group_item = QTableWidgetItem(group)
            group_item.setFlags(group_item.flags() & ~Qt.ItemIsEditable)
            group_item.setToolTip("同类变量放在一起；可拖动整行调整顺序")
            group_item.setBackground(QColor({
                "基本信息": "#eff6ff",
                "时间信息": "#f0fdf4",
                "金额信息": "#fff7ed",
                "辅助变量": "#f5f3ff",
            }.get(group, "#f9fafb")))
            self.var_table.setItem(row, 4, group_item)
        self.var_table.setColumnHidden(
            4, not bool(self.settings.get("show_variable_groups", True)))
        self.var_table.blockSignals(False)
        self._fit_var_columns()
        self._refresh_coverage()

    def _var_is_editable(self, name: str) -> bool:
        if not self.vm or name not in self.vm.variables:
            return False
        var = self.vm.variables[name]
        # 自动编号按用户确认：单人模式也允许手动改，生成时按设置决定语义
        return not (var.rule_mode == "formula" or var.kind == "aux")

    def _editable_var_rows(self) -> List[int]:
        rows = []
        for row in range(self.var_table.rowCount()):
            item = self.var_table.item(row, 0)
            if item and self._var_is_editable(item.text()):
                if not self.var_table.isRowHidden(row):
                    rows.append(row)
        return rows

    def _on_inline_edit_started(self, row: int, _col: int) -> None:
        """编辑中的行放大 1.5 倍并加浅色底。"""
        if row < 0 or row >= self.var_table.rowCount():
            return
        self._restore_inline_row(row)
        old_height = self.var_table.rowHeight(row)
        backgrounds = []
        for col in range(self.var_table.columnCount()):
            item = self.var_table.item(row, col)
            if item is not None:
                backgrounds.append((item, item.background()))
                item.setBackground(QColor("#dbeafe"))
        self._inline_states[row] = (old_height, backgrounds)
        self.var_table.setRowHeight(row, max(30, int(old_height * 1.5)))

    def _restore_inline_row(self, row: int) -> None:
        state = self._inline_states.pop(row, None)
        if not state:
            return
        old_height, backgrounds = state
        for item, brush in backgrounds:
            try:
                item.setBackground(brush)
            except RuntimeError:
                pass
        if 0 <= row < self.var_table.rowCount():
            self.var_table.setRowHeight(row, old_height or 30)

    def _on_inline_edit_finished(self, row: int, _col: int) -> None:
        self._restore_inline_row(row)

    def _on_inline_move(self, row: int, _col: int, kind: str) -> None:
        """回车/Tab 提交后跳到下一个可编辑变量；反向则 Shift+Tab。"""
        rows = self._editable_var_rows()
        if not rows:
            return
        if kind == "backtab":
            target = next((r for r in reversed(rows) if r < row), None)
        else:
            target = next((r for r in rows if r > row), None)
        if target is None:
            return
        self.var_table.selectRow(target)
        self.var_table.setCurrentCell(target, 1)
        self.var_table.scrollToItem(self.var_table.item(target, 0))
        self.var_table.edit(self.var_table.model().index(target, 1))

    def _on_variable_row_dropped(self, source: int, target: int) -> None:
        """拖动整行到目标位置：移动数据而不是覆盖单元格，源行不会空白。"""
        if not self.vm:
            return
        order = list(self.vm.variables)
        if not 0 <= source < len(order):
            return
        name = order.pop(source)
        if target > source:
            target -= 1
        target = max(0, min(target, len(order)))
        order.insert(target, name)
        self._save_variable_order(order)
        self._refresh_var_table()
        if 0 <= target < self.var_table.rowCount():
            self.var_table.selectRow(target)
        self._log(f"已调整「{name}」的位置（保存为自定义顺序）")

    def _on_var_header_menu(self, pos) -> None:
        """变量表头右键：复制整列或按此列排序。"""
        column = self.var_table.horizontalHeader().logicalIndexAt(pos)
        if column < 0:
            return
        from PySide6.QtWidgets import QMenu
        from ui.table_copy import copy_table
        header_item = self.var_table.horizontalHeaderItem(column)
        label = header_item.text() if header_item else f"第{column + 1}列"
        menu = QMenu(self)
        act_copy = menu.addAction(f"复制整列（{label}）")
        act_sort = menu.addAction(f"按「{label}」排序")
        chosen = menu.exec(self.var_table.horizontalHeader().mapToGlobal(pos))
        if chosen == act_copy:
            copy_table(self.var_table, "column", col=column)
            self._log(f"已复制整列：{label}")
        elif chosen == act_sort:
            self._on_var_header_sort(column)

    def _on_var_header_sort(self, column: int) -> None:
        """点击变量表头按该列排序；排序结果保存为自定义变量顺序。"""
        if not self.vm or column < 0:
            return
        descending = (self._var_sort_col == column and not self._var_sort_desc)
        self._var_sort_col = column
        self._var_sort_desc = descending

        def key(name: str):
            item = None
            for row in range(self.var_table.rowCount()):
                name_item = self.var_table.item(row, 0)
                if name_item and name_item.text() == name:
                    item = self.var_table.item(row, column)
                    break
            text = item.text().strip() if item else ""
            try:
                return (0, float(text.replace(",", "")))
            except ValueError:
                return (1, text.casefold())

        order = sorted(self.vm.variables, key=key, reverse=descending)
        self._save_variable_order(order)
        self.var_table.horizontalHeader().setSortIndicatorShown(True)
        self.var_table.horizontalHeader().setSortIndicator(
            column, Qt.DescendingOrder if descending else Qt.AscendingOrder)
        self._refresh_var_table()

    def _save_variable_order(self, order: List[str]) -> None:
        """保存某业务的变量顺序，并切换到自定义排序。"""
        if not self.vm or len(order) != len(self.vm.variables):
            return
        self.vm.variables = {name: self.vm.variables[name] for name in order}
        all_orders = dict(self.settings.get("custom_variable_order", {}) or {})
        all_orders[self.vm.business_name] = list(order)
        self.settings.set("custom_variable_order", all_orders)
        self.settings.set("variable_order", "custom")

    def _on_var_table_menu(self, pos) -> None:
        """变量行右键：上移/下移/置顶/置底（拖拽不灵时的稳妥方式）。"""
        if not self.vm:
            return
        row = self.var_table.rowAt(pos.y())
        if row < 0:
            return
        name_item = self.var_table.item(row, 0)
        if not name_item:
            return
        from PySide6.QtWidgets import QMenu
        from ui.table_copy import copy_table
        column = self.var_table.columnAt(pos.x())
        menu = QMenu(self)
        act_copy_row = menu.addAction("复制整行")
        act_copy_cell = menu.addAction("复制当前单元格")
        act_copy_col = menu.addAction("复制整列")
        menu.addSeparator()
        act_up = menu.addAction("上移一行")
        act_down = menu.addAction("下移一行")
        act_top = menu.addAction("移到最前")
        act_bottom = menu.addAction("移到最后")
        chosen = menu.exec(self.var_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_copy_row:
            copy_table(self.var_table, "row", row=row)
            self._log(f"已复制整行：{name_item.text()}")
            return
        if chosen == act_copy_cell:
            copy_table(self.var_table, "cell", row=row,
                       col=column if column >= 0 else 1)
            self._log(f"已复制「{name_item.text()}」所在单元格")
            return
        if chosen == act_copy_col:
            if column >= 0:
                copy_table(self.var_table, "column", col=column)
                self._log("已复制整列")
            return
        order = list(self.vm.variables)
        name = name_item.text()
        if name not in order:
            return
        index = order.index(name)
        target = index
        if chosen == act_up:
            target = max(0, index - 1)
        elif chosen == act_down:
            target = min(len(order) - 1, index + 1)
        elif chosen == act_top:
            target = 0
        elif chosen == act_bottom:
            target = len(order) - 1
        if target == index:
            return
        order.pop(index)
        order.insert(target, name)
        self._save_variable_order(order)
        self._refresh_var_table()
        self.var_table.selectRow(target)
        self._log(f"已调整「{name}」的位置（保存为自定义顺序）")

    def _refresh_coverage(self) -> None:
        """显示当前变量表的填写覆盖情况。"""
        if not self.vm:
            self.coverage_label.setText("")
            return
        resolved = getattr(self, "_last_resolved", {}) or {}
        regular = {name: var for name, var in self.vm.variables.items()
                   if var.kind != "aux"}
        aux_count = len(self.vm.variables) - len(regular)
        total = len(regular)
        filled = sum(
            1 for name, var in regular.items()
            if str(resolved.get(name, var.value) or "").strip())
        missing = []
        optional_empty = []
        for name, var in regular.items():
            if var.rule_mode == "formula":
                continue
            has_default = bool(var.default_expr or (var.rule_mode == "default" and var.rule_expr))
            if str(var.value or "").strip() or has_default:
                continue
            if var.required:
                missing.append(name)
            else:
                optional_empty.append(name)

        parts = [f"已填写 {filled}/{total}"]
        if aux_count:
            parts.append(f"辅助变量 {aux_count}")
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
            name = name_item.text()
            var = self.vm.variables.get(name)
            if var is not None and (var.rule_mode == "formula" or var.kind == "aux"):
                self._refresh_var_table()
                return
            if name in self._auto_field_names():
                # 手动改编号：默认只用于本次，账本不动；可在设置里改成写账本
                self._manual_numbers[name] = item.text().strip()
            self.vm.set_value(name, item.text())
            self._refresh_coverage()
            self._refresh_formula_cells()

    def _refresh_formula_cells(self) -> None:
        """来源值变化时只刷新公式/辅助变量的单元格，不重建整张表。"""
        if not self.vm:
            return
        try:
            resolved = self.vm.get_all_resolved()
        except Exception:
            return
        self.var_table.blockSignals(True)
        for row in range(self.var_table.rowCount()):
            name_item = self.var_table.item(row, 0)
            value_item = self.var_table.item(row, 1)
            if not name_item or not value_item:
                continue
            var = self.vm.variables.get(name_item.text())
            if var is None or not (var.rule_mode == "formula" or var.kind == "aux"):
                continue
            value_item.setText(str(resolved.get(name_item.text(), "") or ""))
            if var.rule_error:
                value_item.setBackground(QColor("#fee2e2"))
                value_item.setToolTip(f"公式计算失败：{var.rule_error}")
            else:
                value_item.setBackground(QColor("#ecfeff" if var.kind == "aux" else "#e0f2fe"))
                value_item.setToolTip("自动计算，不需要手填")
        self.var_table.blockSignals(False)

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
        computed_fields = {
            name for name, var in self.vm.variables.items()
            if var.rule_mode == "formula" or var.kind == "aux"
        }
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
                if name in auto_fields or name in computed_fields:
                    continue  # 自动编号/公式/辅助变量不接受粘贴
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
                if name_item.text() not in auto_fields and name_item.text() not in computed_fields:
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
        self._manual_numbers = {}
        self._set_history_numbers("", {})
        self._reset_generated_auto()
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
            self._set_history_numbers("", {})
            self._reset_generated_auto()
            self._batch_generate(dialog.multi_results)
            return

        # 单人模式：回填到变量管理器
        if dialog.result:
            self._set_history_numbers("", {})
            self._reset_generated_auto()
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

    def _remember_history(self, business_name: str, vm: VariableManager,
                          resolved: Dict[str, Any], output_dir: str = "") -> None:
        """把本次生成的数据写入历史（只存手动值 + 自动编号）。"""
        if vm is None:
            return
        auto_fields = self._auto_field_names()
        values: Dict[str, str] = {}
        auto_numbers: Dict[str, str] = {}
        for name, var in vm.variables.items():
            if var.kind == "aux" or var.rule_mode == "formula":
                continue
            if name in auto_fields:
                value = resolved.get(name, var.value)
                if str(value or "").strip():
                    auto_numbers[name] = str(value)
                continue
            if str(var.value or "").strip():
                values[name] = str(var.value)
        name = str(resolved.get("姓名") or resolved.get("客户名") or "").strip()
        id_card = str(resolved.get("身份证号") or "").strip()
        append_history(
            business_name, values, auto_numbers,
            name=name, id_tail=id_card[-4:] if id_card else "",
            output_dir=output_dir,
        )

    def _on_history(self) -> None:
        """历史数据：只填变量，不自动生成。"""
        if not self.current_business or not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        dialog = HistoryDialog(self.current_business.name, self)
        if dialog.exec() != QDialog.Accepted:
            return
        record = dialog.selected_record
        if not record:
            return
        has_values = any(str(var.value).strip() for var in self.vm.variables.values())
        if has_values:
            ret = QMessageBox.question(
                self, "载入历史数据",
                "当前变量表已有内容，载入历史会替换它们。是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self.vm.clear_values()
        self._reset_generated_auto()
        auto_fields = self._auto_field_names()
        values = record.get("values", {}) or {}
        for name, value in values.items():
            if name not in self.vm.variables or name in auto_fields:
                continue
            var = self.vm.variables[name]
            if var.rule_mode == "formula" or var.kind == "aux":
                continue
            self.vm.set_value(name, value)
        self._set_history_numbers(
            self.current_business.name, record.get("auto_numbers", {}) or {})
        self._last_output_dir = str(record.get("output_dir", "") or "") or self._last_output_dir
        self._refresh_var_table()
        rows = self._editable_var_rows()
        if rows:
            self.var_table.selectRow(rows[0])
            self.var_table.setCurrentCell(rows[0], 1)
        self._log(f"已载入历史数据：{record.get('name') or '（未命名）'}，请修改后重新生成")

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
        self._set_history_numbers("", {})
        self._reset_generated_auto()
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
        for i, person_vars in enumerate(people_results, 1):
            person_vm = VariableManager(
                business_name=self.current_business.name,
                strip_invisible=bool(self.settings.get("strip_invisible_chars", True)),
            )
            person_vm.init_from_template_vars(
                self._ordered_names(self.current_business),
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
                "validation": self._collect_validation_issues(resolved),
            })

        missing_people = [p for p in prepared if p["missing"]]
        unknown_people = [p for p in prepared if "未知客户" in p["folder"]]
        validation_people = [p for p in prepared if p["validation"]]
        if missing_people or unknown_people or validation_people:
            missing_items = [f"{p['name']}：{'、'.join(p['missing'][:8])}" for p in missing_people]
            warnings = []
            if unknown_people:
                warnings.append(
                    "【客户名】以下人没有识别到客户名/姓名，输出目录会使用“未知客户”：\n  "
                    + "、".join(p["name"] for p in unknown_people[:8]))
            if validation_people:
                val_lines = ["【校验不通过】以下人员的值可能填错："]
                for p in validation_people[:8]:
                    first = p["validation"][0]
                    val_lines.append(f"  {p['name']}：{first.variable} {first.message}")
                if len(validation_people) > 8:
                    val_lines.append(f"  …… 另有 {len(validation_people) - 8} 人")
                warnings.append("\n".join(val_lines))

            from ui.preflight_dialog import PreflightDialog
            box = PreflightDialog(
                self,
                title="批量生成前检查",
                headline=(
                    f"将生成 {len(prepared)} 人的文档，"
                    f"每人 {len([t for t in self.current_business.templates if not t.error])} 个模板。"
                ),
                summary_lines=["以下人员的模板变量为空（未填位置会留空）："],
                missing=missing_items,
                missing_label="未填变量的人员（点“详细查看”就地看全部）：",
                extra_warnings=warnings,
                confirm_text="仍然生成",
                cancel_text="返回检查",
            )
            box.exec()
            if not box.confirmed:
                self._log("批量生成已取消：请先补充空变量或确认客户名")
                return

        total_success, total_fail = 0, 0
        all_issues = []
        from core.generate_report import GenerateReport
        merged = GenerateReport(output_dir=self._last_output_dir or "", people_count=len(prepared))
        for item in prepared:
            self._log(f"\n===== 开始生成第{item['index']}人：{item['name']} =====")
            self._log(f"输出目录：{item['folder']}")
            s, f = self._generate_for_variables(item["resolved"])
            total_success += s
            total_fail += f
            # 每人生成后把自己的条目并入总报告，结果窗一屏看全
            person_report = getattr(self, "_last_report", None)
            if person_report:
                for entry in person_report.success:
                    merged.success.append(type(entry)(
                        name=f"{item['name']}·{entry.name}", path=entry.path, kind="ok"))
                for entry in person_report.gen_failures:
                    merged.gen_failures.append(type(entry)(
                        name=f"{item['name']}·{entry.name}", error=entry.error, kind="generate"))
                for entry in person_report.write_failures:
                    merged.write_failures.append(type(entry)(
                        name=f"{item['name']}·{entry.name}", error=entry.error, kind="write"))
            all_issues.extend([
                type(issue)(variable=f"{item['name']}·{issue.variable}", value=issue.value,
                            message=issue.message, rule_scope=issue.rule_scope)
                for issue in item["validation"]
            ])
            if s:
                save_last_data(
                    self.current_business.name,
                    {name: value for name, value in item["resolved"].items() if str(value).strip()},
                )

        merged.validation_issues = all_issues
        merged.output_dir = self._last_output_dir or merged.output_dir
        self._last_report = merged
        self._last_validation_issues = all_issues

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
        computed_fields = {
            name for name, var in self.vm.variables.items()
            if var.rule_mode == "formula" or var.kind == "aux"
        }
        for name, value in dialog.mapping.items():
            if name in auto_fields or name in computed_fields:
                skipped_auto += 1
                continue  # 自动编号/公式/辅助变量由程序计算，导入不覆盖
            if name in self.vm.variables:
                self.vm.set_value(name, value)
            else:
                self.vm.add_custom_variable(name, value)
            count += 1
        self._refresh_var_table()
        note = f"（跳过 {skipped_auto} 个自动编号/计算变量）" if skipped_auto else ""
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
                "如果要一批人（每行一个人），请用【批量填充】窗口里的「下载空模板」。")
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

    def _assign_auto_numbers(self, values: Dict[str, str], business_name: str,
                             manual: Optional[Dict[str, str]] = None,
                             skip_fields: Optional[set] = None) -> Dict[str, str]:
        """给一条待生成数据发放编号；返回各字段原来的 last，供失败回退。

        单人模式用 self._manual_numbers；批量模式由名单窗口显式传入。
        skip_fields：用户选择"沿用原值"的字段，本次不发放自动号。
        """
        config = self.settings.get("auto_number_fields", {}) or {}
        if not isinstance(config, dict) or not config:
            return {}
        skip_fields = skip_fields or set()
        book = self._number_book(business_name)
        previous: Dict[str, str] = {}
        mode = str(self.settings.get("number_manual_mode", "once") or "once")
        manual_values = manual if isinstance(manual, dict) else self._manual_numbers
        for field in config:
            field = str(field or "").strip()
            if not field or field in skip_fields:
                continue
            locked = ""
            if self._locked_business == business_name:
                locked = str(self._locked_numbers.get(field, "") or "")
            if locked:
                # 历史数据沿用原编号：不消耗台账，也不参与失败回退
                values[field] = locked
                continue
            previous[field] = str((book.data.get(field) or {}).get("last") or "")
            number = resolve_manual(
                book, field, str(manual_values.get(field, "") or ""), mode)
            if number:
                values[field] = number
        return previous

    def _rollback_auto_numbers(self, business_name: str, previous: Dict[str, str]) -> None:
        if not previous:
            return
        book = self._number_book(business_name)
        for field, last in previous.items():
            book.rollback(field, last)

    def _set_history_numbers(self, business_name: str, numbers: Dict[str, str]) -> None:
        """历史数据载入后沿用原编号。"""
        cleaned = {str(k): str(v) for k, v in (numbers or {}).items() if str(v).strip()}
        self._locked_business = business_name if cleaned else ""
        self._locked_numbers = cleaned
        if cleaned:
            text = "、".join(f"{name} {number}" for name, number in cleaned.items())
            self.history_banner.setText(f"已载入历史记录，沿用原编号：{text}")
            self.history_banner.show()
            self.btn_new_number.show()
        else:
            self.history_banner.hide()
            self.btn_new_number.hide()

    def _release_locked_numbers(self) -> None:
        """改用新编号：解除历史编号锁定。"""
        self._locked_business = ""
        self._locked_numbers = {}
        self.history_banner.hide()
        self.btn_new_number.hide()
        self._refresh_var_table()
        self._log("已改用新编号，下次生成按当前顺序发号")

    def _reset_generated_auto(self) -> None:
        """清掉“本次已生成”编号，让表格回到显示下一个号。"""
        self._generated_auto_business = ""
        self._generated_auto_numbers = {}

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
            locked = ""
            if self._locked_business == self.current_business.name:
                locked = str(self._locked_numbers.get(field, "") or "")
            nxt = locked or book.peek(field)
            if nxt:
                parts.append(f"{field} {nxt}" + ("（历史）" if locked else ""))
        return ("下个编号：" + "；".join(parts)) if parts else ""

    def _refresh_number_hint(self) -> None:
        """左下角显示当前各自动编号字段的下一个号码。"""
        if not hasattr(self, "lbl_next_number"):
            return
        self.lbl_next_number.setText(self._number_hint_text())
        config = self.settings.get("auto_number_fields", {}) or {}
        has_auto = isinstance(config, dict) and bool(config) and bool(self.current_business)
        if hasattr(self, "btn_fix_number"):
            self.btn_fix_number.setVisible(has_auto)

    def _on_fix_number(self) -> None:
        """主界面快速改下一次自动编号。"""
        if not self.current_business:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        config = self.settings.get("auto_number_fields", {}) or {}
        fields = [str(f).strip() for f in config if str(f).strip()] if isinstance(config, dict) else []
        if not fields:
            QMessageBox.information(
                self, "没有启用自动编号",
                "请先到【设置】→【配置自动编号…】勾选变量并填起始号。")
            return
        if self._locked_numbers:
            ret = QMessageBox.question(
                self, "当前沿用历史编号",
                "当前正在沿用历史档案号。修改编号后会改为按新编号生成，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
            self._release_locked_numbers()
        from ui.number_fix_dialog import NumberFixDialog
        book = self._number_book(self.current_business.name)
        dialog = NumberFixDialog(fields, book, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._reset_generated_auto()
        self._refresh_number_hint()
        self._refresh_var_table()
        self._log("已修改下一次自动编号")

    def _on_variable_rules(self) -> None:
        """打开“变量默认值与计算”窗口，保存后刷新变量表。"""
        if not self.current_business:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        from ui.variable_rules_dialog import VariableRulesDialog
        business = self.current_business
        template_vars = ordered_variable_names(business, "template")
        current = {name: var.value for name, var in (self.vm.variables.items() if self.vm else [])}
        manual_before = {
            name: var.value for name, var in (self.vm.variables.items() if self.vm else [])
            if str(var.value or "").strip()
        }
        dialog = VariableRulesDialog(
            business.name, template_vars, current_values=current,
            legacy_defaults={
                name: var.default_expr for name, var in (self.vm.variables.items() if self.vm else [])
                if var.default_expr
            },
            parent=self,
        )
        dialog.exec()
        if not getattr(dialog, "changed", False):
            return
        self._load_variables(business)
        if self.vm:
            for name, value in manual_before.items():
                if name in self.vm.variables:
                    self.vm.set_value(name, value)
        self._refresh_var_table()
        self._refresh_number_hint()
        self._log("变量默认值/计算规则已更新")

    def _resolve_record(self, business: BusinessInfo,
                        record: Dict[str, str]) -> Tuple[Dict[str, Any], VariableManager]:
        """按当前变量规则计算名单中的一个人（默认值/公式/辅助变量）。"""
        person_vm = VariableManager(
            business_name=business.name,
            strip_invisible=bool(self.settings.get("strip_invisible_chars", True)),
            apply_defaults_on_empty=False,
        )
        person_vm.init_from_template_vars(
            self._ordered_names(business), business.optional_variables)
        for name, value in record.items():
            if name in person_vm.variables:
                person_vm.set_value(name, value)
            else:
                person_vm.add_custom_variable(name, value)
        effective = person_vm.get_all_resolved()
        for name, value in effective.items():
            var = person_vm.variables.get(name)
            if var is None:
                continue
            if (name in record or var.export_summary
                    or var.rule_mode in ("default", "formula")
                    or bool(var.default_expr)):
                record[name] = "" if value is None else str(value)
        resolved = format_output_values(
            effective,
            date_format=self.settings.get("date_format"),
            range_separator=self.settings.get("date_range_separator"),
        )
        return resolved, person_vm

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
        template_vars = self._ordered_names(business)
        optional_vars = list(business.optional_variables)
        batch_items: List[Dict[str, str]] = []
        batch_number_choice = {"done": False, "skip": set()}

        def _ask_number_overwrite(record: Dict[str, str]) -> set:
            """批量模式只弹一次编号覆盖确认，后续行沿用选择。"""
            if batch_number_choice["done"]:
                return batch_number_choice["skip"]
            batch_number_choice["done"] = True
            from core.autonumber import detect_number_overwrites
            cfg = self.settings.get("auto_number_fields", {}) or {}
            will = detect_number_overwrites(record, cfg, locked={})
            if not will:
                return set()
            box = QMessageBox(self)
            box.setWindowTitle("编号会被覆盖")
            box.setText(
                "名单里有人的编号列已填了值，但启用了自动编号，生成时会被覆盖：\n"
                + "、".join(will)
                + "\n\n这批统一怎么处理？")
            btn_keep = box.addButton("沿用名单里填的值", QMessageBox.YesRole)
            btn_auto = box.addButton("用自动编号覆盖", QMessageBox.NoRole)
            box.setDefaultButton(btn_keep)
            box.exec()
            skip = set(will) if box.clickedButton() == btn_keep else set()
            batch_number_choice["skip"] = skip
            return skip

        def generate_one(record: Dict[str, str]) -> Tuple[int, int]:
            # 名单生成期间临时把当前业务对齐，复用现有渲染流程
            self.current_business = business
            manual = record.pop("__manual_numbers__", None) or {}
            if not isinstance(manual, dict):
                manual = {}
            # 真实生成时才发放档案号：没有文档就不会占号，避免断号
            skip_nums = _ask_number_overwrite(record)
            number_previous = self._assign_auto_numbers(
                record, business.name, manual=manual, skip_fields=skip_nums)
            resolved, person_vm = self._resolve_record(business, record)
            ok, fail = self._generate_for_variables(resolved)
            if not ok and fail:
                self._rollback_auto_numbers(business.name, number_previous)
            if ok:
                self._remember_history(
                    business.name, person_vm, resolved, self._last_output_dir or "")
            batch_items.extend(getattr(self, "_last_generated_items", []))
            self._refresh_number_hint()
            return ok, fail

        old_window = getattr(self, "_roster_window", None)
        if (old_window is not None and old_window.isVisible()
                and getattr(old_window, "business_name", "") == business.name):
            old_window.refresh_template(template_vars, optional_vars)
            old_window.show()
            old_window.raise_()
            old_window.activateWindow()
            return
        if old_window is not None:
            old_window.close()

        formula_fields = []
        if self.vm:
            formula_fields = [name for name, var in self.vm.variables.items()
                              if var.rule_mode == "formula"]
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
            on_start=batch_items.clear,
            settings=self.settings,
            formula_fields=formula_fields,
            auto_fields=list(self._auto_field_names()),
            resolve_record=lambda rec: self._resolve_record(business, rec)[0],
            parent=self,
        )
        self._roster_window = window  # 防止被回收
        window.show()
        window.raise_()
        window.activateWindow()

    # ---------- 生成文档 ----------

    def _collect_validation_issues(self, resolved: Dict[str, Any]) -> list:
        """按当前设置对变量值运行校验，返回问题列表（关闭/无规则时为空）。"""
        if not self.settings.get("validation_enabled", True):
            return []
        try:
            from core.validator import collect_issues, load_document
            template_vars = list(self.vm.variables.keys()) if self.vm else []
            return collect_issues(
                resolved,
                load_document(),
                business_name=self.current_business.name if self.current_business else "",
                enabled=True,
                use_builtin=bool(self.settings.get("validation_builtin_enabled", True)),
                variable_names=template_vars,
            )
        except Exception as exc:
            self._log(f"[校验] 校验器异常，已跳过：{exc}")
            return []

    def _on_generate(self) -> None:
        """一键生成文档：预检 -> 解析变量 -> 渲染模板 -> 输出到业务子文件夹"""
        if not self.current_business or not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        if not self.settings.output_root_dir:
            QMessageBox.information(self, "提示", "请先设置输出根目录")
            return

        resolved = self.vm.get_output_values()
        for name, error in self.vm.rule_errors():
            self._log(f"[计算失败] {name}：{error}")
        # N6：模板已填编号 + 开自动编号会静默覆盖，生成前先让用户选择
        from core.autonumber import detect_number_overwrites
        overwrite_config = self.settings.get("auto_number_fields", {}) or {}
        locked_now = self._locked_numbers if self._locked_business == self.current_business.name else {}
        will_overwrite = detect_number_overwrites(resolved, overwrite_config, locked=locked_now)
        skip_number_fields = set()
        if will_overwrite:
            box = QMessageBox(self)
            box.setWindowTitle("编号会被覆盖")
            box.setText(
                "这些变量你已经填了值，但启用了自动编号，生成时会被账本号覆盖：\n"
                + "、".join(will_overwrite)
                + "\n\n请选择处理方式：")
            btn_keep = box.addButton("沿用我已填的值", QMessageBox.YesRole)
            btn_auto = box.addButton("用自动编号覆盖", QMessageBox.NoRole)
            btn_cancel = box.addButton("取消生成", QMessageBox.RejectRole)
            box.setDefaultButton(btn_keep)
            box.exec()
            clicked = box.clickedButton()
            if clicked == btn_cancel:
                return
            if clicked == btn_keep:
                skip_number_fields = set(will_overwrite)
        number_previous = self._assign_auto_numbers(
            resolved, self.current_business.name, skip_fields=skip_number_fields)
        missing = collect_empty_variables(self.current_business, resolved)
        validation_issues = self._collect_validation_issues(resolved)
        folder_name = self.output_mgr.build_subfolder_name(self.current_business.name, resolved)
        unknown_customer = "未知客户" in folder_name
        template_count = len([t for t in self.current_business.templates if not t.error])

        if missing or unknown_customer or validation_issues:
            warnings = []
            if unknown_customer:
                warnings.append("【客户名】没有识别到客户名/姓名，目录会使用“未知客户”。建议先填写客户名或姓名。")
            if validation_issues:
                val_lines = ["【校验不通过】以下变量的值可能填错："]
                for issue in validation_issues[:8]:
                    val_lines.append(f"  {issue.variable}：{issue.message}")
                if len(validation_issues) > 8:
                    val_lines.append(f"  …… 另有 {len(validation_issues) - 8} 项")
                warnings.append("\n".join(val_lines))

            from ui.preflight_dialog import PreflightDialog
            box = PreflightDialog(
                self,
                title="生成前检查",
                headline="即将生成文档，请确认以下信息。",
                summary_lines=[f"输出目录：{folder_name}", f"模板：{template_count} 个"],
                missing=missing,
                extra_warnings=warnings,
            )
            box.exec()
            if not box.confirmed:
                self._rollback_auto_numbers(self.current_business.name, number_previous)
                self._refresh_number_hint()
                self._refresh_var_table()
                self._log("生成已取消：请先补充空变量或确认客户名")
                return

        self._log(f"\n准备生成：{folder_name}（{template_count} 个模板）")
        # 用户确认"仍然生成"后，校验问题不再拦截，但要带进结果汇总窗一屏显示
        self._last_validation_issues = validation_issues
        success, fail = self._generate_for_variables(resolved)
        if not success and fail:
            # 全部失败：退回号码，避免占用造成断号
            self._rollback_auto_numbers(self.current_business.name, number_previous)
        self._refresh_number_hint()
        if success:
            auto_fields = self._auto_field_names()
            self._generated_auto_business = self.current_business.name
            self._generated_auto_numbers = {
                field: str(resolved.get(field, "") or "")
                for field in auto_fields if str(resolved.get(field, "") or "").strip()
            }
            # 手工号按"本次"语义用掉；book 模式也已写进账本，不应重复使用
            self._manual_numbers = {}
        else:
            self._generated_auto_business = ""
            self._generated_auto_numbers = {}
        self._refresh_var_table()
        if success:
            self._after_generate_files(list(getattr(self, "_last_generated_items", [])))
        if success:
            save_last_data(
                self.current_business.name,
                {name: var.value for name, var in self.vm.variables.items() if str(var.value).strip()},
            )
            self._remember_history(
                self.current_business.name, self.vm, resolved,
                self._last_output_dir or "")
        self._log(f"\n生成完成：成功 {success} 个，失败 {fail} 个")
        self._show_generate_result(success, fail)

    def _show_generate_result(self, success: int, fail: int) -> None:
        """用一个醒目的汇总窗一屏看全：状态带 + 分区明细，不再弹多个窗口。"""
        from ui.generate_result_dialog import GenerateResultDialog

        report = getattr(self, "_last_report", None)
        if report is None:
            from core.generate_report import GenerateReport
            report = GenerateReport(output_dir=self._last_output_dir)
            report.summary_line = lambda: f"成功 {success} 个，失败 {fail} 个"
        report.output_dir = self._last_output_dir or report.output_dir
        report.validation_issues = list(getattr(self, "_last_validation_issues", []) or [])

        def next_order():
            dialog.accept()
            self._clear_current_values(confirm=True)

        dialog = GenerateResultDialog(
            report, self,
            on_open_output=self._open_last_output,
            extra_buttons=[("下一单（清空）", next_order)],
        )

        # 生成成功且开了自动打开：先弹出资源管理器，再显示结果框
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

        # 先打印再正常打开：避免 Word/Excel 先打开占用文件，打印时只能以只读方式打开。
        if self.settings.get("auto_print_after_open", False):
            printed, print_failed = print_files(
                targets,
                copies=int(self.settings.get("print_copies", 1) or 1),
                printer=str(self.settings.get("printer_name", "") or ""),
            )
            self._log(f"[打印] 已发送 {printed} 个文件到默认打印机"
                      + (f"，{print_failed} 个失败" if print_failed else ""))
        opened, failed = open_files(targets)
        self._log(f"[打开] 已打开 {opened} 个文件" + (f"，{failed} 个失败" if failed else ""))

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
        from core.generate_report import GenerateReport
        report = GenerateReport(output_dir=self.output_mgr.output_root_dir if hasattr(self.output_mgr, "output_root_dir") else "")
        self._last_report = report
        try:
            output_dir = self.output_mgr.get_output_dir(self.current_business.name, resolved)
            self._last_output_dir = output_dir  # 记录供打开目录
            report.output_dir = output_dir
        except OutputError as e:
            QMessageBox.critical(self, "输出错误", str(e))
            report.ledger_error = str(e)
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
                report.add_item(tmpl.name, error=tmpl.error, kind="generate")
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
                # 模板本身可能是只读的，复制出来的结果也会带只读属性；
                # 生成结果必须可编辑，这里主动去掉只读。
                if not os.access(out_path, os.W_OK):
                    try:
                        os.chmod(out_path, stat.S_IREAD | stat.S_IWRITE)
                    except OSError:
                        pass
                report.add_item(tmpl.name, path=out_path, kind="ok")
                success += 1
            except RenderError as e:
                self._log(f"[失败] {tmpl.name}：{e}")
                logger.error(f"生成失败 {tmpl.name}：{e}")
                error_text = str(e)
                kind = "write" if any(k in error_text for k in ("拒绝访问", "Permission", "占用", "保存", "写入")) else "generate"
                report.add_item(tmpl.name, error=error_text, kind=kind)
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
        """根据 settings 中的配置创建快捷键；输入框/单元格编辑态自动让位。"""
        values = dict(DEFAULT_SETTINGS.get("shortcuts", {}))
        saved = self.settings.get("shortcuts", {}) or {}
        if isinstance(saved, dict):
            values.update(saved)
        self._shortcuts = []
        action_map = {
            "smart_paste": self._on_smart_paste,
            "generate": self._on_generate,
            "rescan": self._scan_businesses,
            "reuse": self._on_reuse_last,
            "next_case": self._on_next_case,
            "open_output": self._open_last_output,
        }
        for key, action in action_map.items():
            seq = str(values.get(key) or "").strip()
            if not seq:
                continue
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.activated.connect(self._guarded_action(action))
            self._shortcuts.append(shortcut)

    @staticmethod
    def _guarded_action(action):
        """光标在输入框里时不触发窗口级快捷键，避免打断录入。"""
        from PySide6.QtWidgets import QPlainTextEdit

        def wrapper():
            widget = QApplication.focusWidget()
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):
                return
            action()
        return wrapper

    def _on_settings(self) -> None:
        """打开设置对话框（排序、日期格式、输出命名、快捷键）"""
        variable_names = []
        if self.current_business:
            variable_names = self._ordered_names(self.current_business)
        old_order = self.settings.get("variable_order", "smart")
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
            # 主题可能变了：立即给主窗口换色，无需重启
            self.setStyleSheet(current_style())
            if getattr(dialog, "restored_config", False):
                self._reload_after_config_restore()
                return
            # 重新创建快捷键
            for sc in getattr(self, "_shortcuts", []):
                sc.setEnabled(False)
            self._create_shortcuts()

            if dialog.cleared_last_data:
                self._last_paste_result = None

            # 排序或不可见字符开关变了：保留当前值，重建变量表让新设置立即生效
            new_strip = bool(self.settings.get("strip_invisible_chars", True))
            if self.current_business and (
                self.settings.get("variable_order", "smart") != old_order
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

    def _reload_after_config_restore(self) -> None:
        """配置包恢复后：重新扫描业务、快捷键和当前变量表。"""
        old_roster = getattr(self, "_roster_window", None)
        if old_roster is not None:
            try:
                old_roster.close()
            except Exception:
                pass
            self._roster_window = None
        name = self.current_business.name if self.current_business else ""
        for sc in getattr(self, "_shortcuts", []):
            sc.setEnabled(False)
        self._shortcuts = []
        self._create_shortcuts()
        self._number_books.clear()
        self._refresh_path_labels()
        self._scan_businesses()
        if name:
            for business in self.businesses:
                if business.name == name:
                    self.current_business = business
                    self._load_variables(business)
                    break
        self._refresh_number_hint()
        self._refresh_var_table()
        self._log("配置已恢复，界面已按新配置刷新")

    def _on_tutorial(self) -> None:
        """打开使用教程弹窗（内容见 ui/style.py TUTORIAL_HTML）"""
        TutorialDialog(self).exec()


class TutorialDialog(QDialog):
    """使用教程弹窗：富文本展示操作步骤与常见问题"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用教程 · 3 步上手")
        self.resize(820, 700)
        self.setStyleSheet(current_style())
        icon_file = asset_path("docfill.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.document().setDocumentMargin(18)
        browser.setHtml(current_tutorial_html())
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
        "next_case": "下一单（清空）",
        "open_output": "打开输出目录",
        "import": "批量：导入名单",
        "generate_selected": "批量：生成选中",
        "delete_rows": "批量：删除选中行",
        "export": "批量：导出名单",
        "bulk_set": "批量：批量设值",
    }
    MAIN_SHORTCUTS = ("smart_paste", "generate", "rescan", "reuse",
                      "next_case", "open_output")
    BATCH_SHORTCUTS = ("import", "generate_selected", "delete_rows",
                       "export", "bulk_set")

    def __init__(self, settings, parent=None, variable_names=None, business_name=None,
                 template_names=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(760, 720)
        self.setStyleSheet(build_style(current_theme()))  # 自包含样式：跟随当前主题
        self.settings = settings
        self.variable_names = list(variable_names or [])
        self.template_names = list(template_names or [])
        self.business_name = business_name or ""
        self.cleared_last_data = False
        self._shortcut_inputs = {}
        # 打开/打印配置：_build_ui 里的摘要刷新、配置窗口和保存都依赖它。
        # 上一轮把旧版平铺设置页删掉后漏了初始化，导致点【设置】直接 AttributeError。
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
        self._build_ui()

    def _build_ui(self) -> None:
        """设置页按用途分页，避免所有选项平铺成长列表。"""
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)

        def new_tab(title: str):
            pane = QWidget()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(pane)
            layout = QVBoxLayout(pane)
            tabs.addTab(scroll, title)
            return layout

        def section(layout, title: str, hint: str = ""):
            label = QLabel(f"<b>{title}</b>")
            label.setObjectName("formSection")  # 分节头：色条 + 浅底，给眼睛落点
            layout.addWidget(label)
            if hint:
                note = QLabel(hint)
                note.setWordWrap(True)
                note.setStyleSheet("color:#6b7280; font-size:9pt;")
                layout.addWidget(note)

        # ---------- 1. 常用 ----------
        common = new_tab("常用")
        section(common, "界面主题", "点确定后全部窗口立即换色，重启后仍保持。")
        from ui.style import THEME_ORDER, THEMES
        self.theme_combo = QComboBox()
        for theme_id in THEME_ORDER:
            self.theme_combo.addItem(THEMES[theme_id]["label"], theme_id)
        theme_index = self.theme_combo.findData(current_theme())
        self.theme_combo.setCurrentIndex(max(theme_index, 0))
        common.addWidget(self.theme_combo)

        section(common, "输出命名与变量表")
        common.addWidget(QLabel("客户名变量（用于“业务_客户名_年月”文件夹命名）："))
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
        common.addWidget(self.customer_combo)

        common.addWidget(QLabel("变量表排序："))
        self.order_combo = QComboBox()
        self.order_combo.addItem("智能分组（基本信息 → 时间 → 金额 → 其他，推荐）", "smart")
        self.order_combo.addItem("模板填写顺序", "template")
        self.order_combo.addItem("字典顺序（按名称排序）", "alphabetical")
        self.order_combo.addItem("自定义（在变量表里拖动整行）", "custom")
        order_index = self.order_combo.findData(self.settings.get("variable_order", "smart"))
        self.order_combo.setCurrentIndex(max(order_index, 0))
        common.addWidget(self.order_combo)

        self.show_groups_checkbox = QCheckBox("显示“分组”列并按组着色（关掉更省空间）")
        self.show_groups_checkbox.setChecked(
            bool(self.settings.get("show_variable_groups", True)))
        common.addWidget(self.show_groups_checkbox)

        common.addWidget(QLabel("身份证号变量（重名文件追加后四位）："))
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
        common.addWidget(self.id_card_combo)

        section(common, "生成之后")
        self.clear_checkbox = QCheckBox("生成成功后自动清空变量表，开始下一单")
        self.clear_checkbox.setChecked(bool(self.settings.get("clear_after_generate", False)))
        common.addWidget(self.clear_checkbox)
        self.open_folder_checkbox = QCheckBox("生成成功后自动打开输出文件夹")
        self.open_folder_checkbox.setChecked(
            bool(self.settings.get("open_folder_after_generate", True)))
        common.addWidget(self.open_folder_checkbox)
        common.addStretch()

        # ---------- 2. 填充与校验 ----------
        fill = new_tab("填充与校验")
        section(fill, "录入辅助")
        self.strip_invisible_checkbox = QCheckBox(
            "自动去除不可见字符（零宽空格、BOM、不换行空格等）")
        self.strip_invisible_checkbox.setChecked(
            bool(self.settings.get("strip_invisible_chars", True)))
        self.strip_invisible_checkbox.setToolTip(
            "从网页/微信/Excel 复制的资料常带肉眼看不见的字符，\n"
            "会导致身份证校验失败、地址匹配不上等问题。")
        fill.addWidget(self.strip_invisible_checkbox)

        self.shrink_checkbox = QCheckBox(
            "内容超出格子时自动缩小字号（保住页数；关闭则绝不改格式）")
        self.shrink_checkbox.setChecked(
            bool(self.settings.get("shrink_overflow_font", True)))
        self.shrink_checkbox.setToolTip(
            "版式保护是默认行为：只替换文字、不动任何格式。\n"
            "唯一例外：当真实数据比占位符长、必然多占行时，\n"
            "允许把该单元格字号适度调小以避免撑到下一页（最多到 70%）。")
        fill.addWidget(self.shrink_checkbox)

        section(fill, "变量校验（生成前查错）",
                "检查身份证校验位、手机号格式等明显错误；规则可自定义，升级不覆盖。")
        self.validation_checkbox = QCheckBox("启用生成前校验（默认开启）")
        self.validation_checkbox.setChecked(bool(self.settings.get("validation_enabled", True)))
        self.validation_checkbox.setToolTip("生成前检查身份证/手机号等格式错误，避免盖章后才发现填错。")
        fill.addWidget(self.validation_checkbox)
        self.builtin_validation_checkbox = QCheckBox("自动校验常见字段（身份证号/手机号/邮箱，无需配置）")
        self.builtin_validation_checkbox.setChecked(bool(self.settings.get("validation_builtin_enabled", True)))
        self.builtin_validation_checkbox.setToolTip(
            "按变量名自动套用内置校验：身份证号含校验位、手机号11位、邮箱格式。"
            "关闭后只保留你自己在【配置校验规则】里写的规则。")
        fill.addWidget(self.builtin_validation_checkbox)
        validation_row = QHBoxLayout()
        self.btn_validation_rules = QPushButton("配置校验规则…")
        self.btn_validation_rules.clicked.connect(self._on_configure_validation)
        validation_row.addWidget(self.btn_validation_rules)
        self.validation_summary = QLabel("")
        self.validation_summary.setWordWrap(True)
        validation_row.addWidget(self.validation_summary, 1)
        fill.addLayout(validation_row)
        self._refresh_validation_summary()
        fill.addStretch()

        # ---------- 3. 日期与编号 ----------
        datetime_tab = new_tab("日期与编号")
        section(datetime_tab, "日期输出格式",
                "内部统一按 YYYY-MM-DD 存储/计算，只在写入文档时转成下面的格式。")
        form = QFormLayout()
        self.date_combo = QComboBox()
        self.date_combo.setEditable(True)
        self.date_combo.addItems(DATE_FORMAT_PRESETS)
        self.date_combo.setCurrentText(
            str(self.settings.get("date_format", DATE_FORMAT_PRESETS[0])
                or DATE_FORMAT_PRESETS[0]))
        form.addRow("全局日期格式：", self.date_combo)
        self.range_combo = QComboBox()
        self.range_combo.setEditable(True)
        self.range_combo.addItems(RANGE_SEPARATOR_PRESETS)
        self.range_combo.setCurrentText(
            str(self.settings.get("date_range_separator", RANGE_SEPARATOR_PRESETS[0])
                or RANGE_SEPARATOR_PRESETS[0]))
        form.addRow("起止连接词：", self.range_combo)
        datetime_tab.addLayout(form)
        hint = QLabel("支持：YYYY、YY、MM、M、DD、D；例如 YYYY年M月D日 → 2026年1月1日")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6b7280;")
        datetime_tab.addWidget(hint)
        self.date_preview = QLabel("")
        self.date_preview.setStyleSheet("color:#0f766e; font-weight:bold;")
        datetime_tab.addWidget(self.date_preview)
        self.date_combo.currentTextChanged.connect(self._update_date_preview)
        self.range_combo.currentTextChanged.connect(self._update_date_preview)
        self._update_date_preview()

        section(datetime_tab, "按变量指定日期格式（可选）",
                "留空=用上面的全局格式。例如“出生日期”填 YYYYMMDD 只影响这一个变量。")
        self._date_override_table = QTableWidget(0, 2)
        self._date_override_table.setHorizontalHeaderLabels(["变量名", "专用格式（留空=全局）"])
        self._date_override_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._date_override_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        overrides = self.settings.get("date_format_overrides", {}) or {}
        if not isinstance(overrides, dict):
            overrides = {}
        date_names = [name for name in self.variable_names if is_date_field(name)]
        for name in list(dict.fromkeys(date_names + list(overrides.keys()))):
            row = self._date_override_table.rowCount()
            self._date_override_table.insertRow(row)
            name_item = QTableWidgetItem(str(name))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self._date_override_table.setItem(row, 0, name_item)
            self._date_override_table.setItem(
                row, 1, QTableWidgetItem(str(overrides.get(name, "") or "")))
        datetime_tab.addWidget(self._date_override_table)
        date_btn = QPushButton("添加变量…")
        date_btn.setObjectName("ghost")
        date_btn.clicked.connect(self._on_add_date_override)
        datetime_tab.addWidget(date_btn)

        section(datetime_tab, "自动编号（档案号 / 管理序号）",
                "勾选变量并填起始号；每生成一份真实文档才 +1，不会断号。")
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
        auto_row.addWidget(self.auto_number_summary, 1)
        datetime_tab.addLayout(auto_row)
        self._refresh_auto_number_summary()

        mode_row = QFormLayout()
        self.number_mode_combo = QComboBox()
        self.number_mode_combo.addItem("仅本次生效，账本不变（推荐）", "once")
        self.number_mode_combo.addItem("同时改账本下一号，后面的人顺延", "book")
        number_index = self.number_mode_combo.findData(
            self.settings.get("number_manual_mode", "once"))
        self.number_mode_combo.setCurrentIndex(max(number_index, 0))
        mode_row.addRow("手动改编号：", self.number_mode_combo)
        datetime_tab.addLayout(mode_row)
        datetime_tab.addStretch()

        # ---------- 4. 批量填充 ----------
        batch = new_tab("批量填充")
        section(batch, "再次导入 Excel 时",
                "同一个业务下可以保存多份名单，顶部下拉自由切换、新建、重命名、删除。")
        self.batch_import_combo = QComboBox()
        self.batch_import_combo.addItem("新建批次，旧批次保留（推荐）", "new_batch")
        self.batch_import_combo.addItem("并入当前选中的批次", "merge_current")
        self.batch_import_combo.addItem("每次导入时询问我", "ask")
        batch_index = self.batch_import_combo.findData(
            self.settings.get("batch_import_mode", "new_batch"))
        self.batch_import_combo.setCurrentIndex(max(batch_index, 0))
        batch.addWidget(self.batch_import_combo)

        section(batch, "批量设值",
                "名单窗口的【批量设值】可选：选中行 / 当前筛选可见行 / 全部行；\n"
                "默认只改选中行并跳过已生成的行。列头右键也能直接进入。")
        section(batch, "名单数据",
                "批次删除会二次确认后直接删除，不做回收站；名单 JSON 损坏时会自动备份并提示。")
        batch.addStretch()

        # ---------- 5. 打印与移交 ----------
        output = new_tab("打印与移交")
        section(output, "打开与打印")
        open_print_row = QHBoxLayout()
        self.btn_open_print = QPushButton("打开与打印…")
        self.btn_open_print.setToolTip("生成后自动打开哪些文件、用什么打印机、打印几份")
        self.btn_open_print.clicked.connect(self._on_configure_open_print)
        open_print_row.addWidget(self.btn_open_print)
        self.open_print_summary = QLabel("")
        self.open_print_summary.setWordWrap(True)
        open_print_row.addWidget(self.open_print_summary, 1)
        output.addLayout(open_print_row)
        self._refresh_open_print_summary()

        section(output, "移交清单（汇总台账）")
        self.handover_checkbox = QCheckBox(
            "启用：每批人员生成后自动追加进一张 Excel 移交清单")
        self.handover_checkbox.setChecked(bool(self.settings.get("handover_enabled", True)))
        output.addWidget(self.handover_checkbox)
        template_row = QHBoxLayout()
        self.handover_template_edit = QLineEdit(
            str(self.settings.get("handover_template", "") or ""))
        self.handover_template_edit.setPlaceholderText(
            "留空=标准表头；可指定你们的《移交表》.xlsx")
        btn_pick = QPushButton("选择模板…")
        btn_pick.clicked.connect(self._on_pick_handover_template)
        template_row.addWidget(QLabel("汇总模板："))
        template_row.addWidget(self.handover_template_edit, 1)
        template_row.addWidget(btn_pick)
        output.addLayout(template_row)

        dedup_row = QHBoxLayout()
        self.handover_dedup_combo = QComboBox()
        for name in (self.variable_names or []):
            self.handover_dedup_combo.addItem(name, name)
        current_dedup = str(self.settings.get("handover_dedup_field", "姓名") or "姓名")
        if self.handover_dedup_combo.findData(current_dedup) < 0:
            self.handover_dedup_combo.addItem(current_dedup, current_dedup)
        self.handover_dedup_combo.setCurrentIndex(
            max(self.handover_dedup_combo.findData(current_dedup), 0))
        dedup_row.addWidget(QLabel("去重依据列："))
        dedup_row.addWidget(self.handover_dedup_combo, 1)
        output.addLayout(dedup_row)
        output.addStretch()

        # ---------- 6. 快捷键与数据 ----------
        keys = new_tab("快捷键与数据")
        section(keys, "快捷键", "格式如 Ctrl+G、F5、Ctrl+Shift+V；留空禁用。重复或无效会在确定时提示。")
        sc = dict(DEFAULT_SETTINGS.get("shortcuts", {}))
        saved_sc = self.settings.get("shortcuts", {}) or {}
        if isinstance(saved_sc, dict):
            sc.update(saved_sc)
        # 两列并排：主窗口 / 批量窗口各一列，省一半垂直空间
        shortcut_columns = QHBoxLayout()
        for group_title, group_keys in (
            ("主窗口", self.MAIN_SHORTCUTS),
            ("批量窗口", self.BATCH_SHORTCUTS),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(f"<b>{group_title}</b>"))
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            for key in group_keys:
                edit = QLineEdit(str(sc.get(key, "") or ""))
                edit.setPlaceholderText("留空则禁用")
                edit.setMaximumWidth(160)  # 快捷键很短，输入框无需占满整行
                self._shortcut_inputs[key] = edit
                form.addRow(f"{self.SHORTCUT_LABELS[key]}：", edit)
            column.addLayout(form)
            column.addStretch()
            shortcut_columns.addLayout(column, 1)
        keys.addLayout(shortcut_columns)

        section(keys, "本机缓存与配置")
        btn_clear_history = QPushButton("清除历史数据…")
        btn_clear_history.setToolTip("删除所有业务保存的历史填充数据，不影响已生成的文件")
        btn_clear_history.clicked.connect(self._on_clear_history)
        keys.addWidget(btn_clear_history)
        btn_clear_cache = QPushButton("清除本业务上次数据")
        btn_clear_cache.setToolTip("只清除本机记住的“上次数据”，不影响模板和已生成文件")
        btn_clear_cache.clicked.connect(self._clear_cached_data)
        keys.addWidget(btn_clear_cache)

        self.restored_config = False
        backup_row = QHBoxLayout()
        btn_backup = QPushButton("导出配置包…")
        btn_backup.clicked.connect(self._on_backup_config)
        btn_restore = QPushButton("导入配置包…")
        btn_restore.clicked.connect(self._on_restore_config)
        backup_row.addWidget(btn_backup)
        backup_row.addWidget(btn_restore)
        backup_row.addStretch()
        keys.addLayout(backup_row)

        about = QLabel(
            f'{APP_NAME} {APP_VERSION} · 作者/联系：daokunn · '
            '<a href="https://github.com/daokunn/docfill">github.com/daokunn/docfill</a>')
        about.setOpenExternalLinks(True)
        about.setStyleSheet("color:#6b7280; font-size:9pt;")
        keys.addWidget(about)
        keys.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_add_date_override(self) -> None:
        name, ok = QInputDialog.getText(self, "添加变量", "要为哪个变量单独指定日期格式？")
        if not ok or not name.strip():
            return
        name = name.strip()
        for row in range(self._date_override_table.rowCount()):
            if self._date_override_table.item(row, 0).text() == name:
                self._date_override_table.setCurrentCell(row, 1)
                return
        row = self._date_override_table.rowCount()
        self._date_override_table.insertRow(row)
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self._date_override_table.setItem(row, 0, item)
        self._date_override_table.setItem(row, 1, QTableWidgetItem(""))
        self._date_override_table.setCurrentCell(row, 1)

    def _refresh_open_print_summary(self) -> None:
        """设置界面里显示打开/打印配置摘要。"""
        if not hasattr(self, "open_print_summary") or not hasattr(self, "open_print_config"):
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

    def _refresh_validation_summary(self) -> None:
        """在设置界面显示当前校验规则数量。"""
        if not hasattr(self, "validation_summary"):
            return
        from core.validator import load_document, merged_rules
        try:
            rules = merged_rules(load_document(), self.business_name)
        except Exception:
            self.validation_summary.setText("")
            return
        enabled = sum(1 for r in rules.values() if r.get("enabled"))
        self.validation_summary.setText(
            f"当前生效 {enabled} 条校验规则" if enabled else "尚未配置；可内置预设快速添加")

    def _on_configure_validation(self) -> None:
        """打开变量校验规则配置窗口。"""
        from ui.validation_rules_dialog import ValidationRulesDialog

        dialog = ValidationRulesDialog(
            business_name=self.business_name,
            template_vars=self.variable_names,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._refresh_validation_summary()

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

    def _on_clear_history(self) -> None:
        """清除所有业务的历史数据（设置窗口里的按钮）。"""
        from core.history_store import clear_history
        ret = QMessageBox.question(
            self, "清除历史数据",
            "将删除所有业务保存的历史填充数据。\n"
            "已生成的 Word/Excel 文件不会删除，模板也不会受影响。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        count = clear_history()
        QMessageBox.information(self, "已清除", f"已删除 {count} 条历史记录。")
        parent = self.parent()
        if hasattr(parent, "_set_history_numbers"):
            parent._set_history_numbers("", {})

    def _on_backup_config(self) -> None:
        """导出设置、别名、规则、名单和编号台账。"""
        from core.config_backup import ConfigBackupError, create_backup, default_backup_name
        from ui.backup_dialog import BackupOptionsDialog
        options = BackupOptionsDialog(self)
        if options.exec() != QDialog.Accepted:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置包", default_backup_name(), "Zip 压缩包 (*.zip)")
        if not path:
            return
        include_history = options.include_history
        try:
            count, _files = create_backup(APP_DIR, path, include_history=include_history)
        except ConfigBackupError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self, "已导出",
            f"已备份 {count} 个配置文件：\n{path}\n\n"
            + ("包含历史数据。" if include_history else "未包含历史数据。")
            + "\n换电脑或升级后可用【导入配置包】恢复。")

    def _on_restore_config(self) -> None:
        """从配置包恢复；恢复前自动备份当前配置。"""
        from core.config_backup import ConfigBackupError, restore_backup
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置包", "", "Zip 压缩包 (*.zip)")
        if not path:
            return
        ret = QMessageBox.question(
            self, "确认恢复配置",
            "将用备份包覆盖当前设置、别名、自定义规则、名单和编号台账。\n"
            "恢复前会自动备份当前配置，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            count, backup_path = restore_backup(APP_DIR, path)
        except ConfigBackupError as exc:
            QMessageBox.critical(self, "恢复失败", str(exc))
            return
        self.settings.reload()
        self.restored_config = True
        extra = f"\n\n恢复前配置已备份到：\n{backup_path}" if backup_path else ""
        QMessageBox.information(
            self, "恢复完成",
            f"已恢复 {count} 个配置项。\n点击“确定”后界面会按新配置刷新。{extra}")
        # 直接关闭设置，避免再点“确定”把旧控件值写回去
        self.accept()
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
        """保存设置；快捷键做合法性和重复校验。"""
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
        canonical_seen: Dict[str, str] = {}
        for key, edit in self._shortcut_inputs.items():
            val = edit.text().strip()
            if not val:
                continue
            sequence = QKeySequence(val)
            if sequence.isEmpty():
                QMessageBox.warning(
                    self, "快捷键无效",
                    f"「{self.SHORTCUT_LABELS[key]}」的快捷键「{val}」无法识别。\n"
                    "请用 Ctrl+G、F5、Ctrl+Shift+V 这样的写法。")
                return
            canonical = sequence.toString().casefold()
            if canonical in canonical_seen:
                QMessageBox.warning(
                    self, "快捷键重复",
                    f"「{self.SHORTCUT_LABELS[key]}」和"
                    f"「{self.SHORTCUT_LABELS[canonical_seen[canonical]]}」"
                    f"都用了「{val}」。\n请改成不同的组合。")
                return
            canonical_seen[canonical] = key
            shortcuts[key] = val

        date_overrides: Dict[str, str] = {}
        for row in range(self._date_override_table.rowCount()):
            name_item = self._date_override_table.item(row, 0)
            format_item = self._date_override_table.item(row, 1)
            if not name_item or not format_item:
                continue
            value = format_item.text().strip()
            if value:
                date_overrides[name_item.text().strip()] = value

        self.settings.set("theme", self.theme_combo.currentData() or "ink")
        self.settings.set("date_format", date_format)
        self.settings.set("date_range_separator", range_separator or "至")
        self.settings.set("date_format_overrides", date_overrides)
        self.settings.set("number_manual_mode",
                          self.number_mode_combo.currentData() or "once")
        self.settings.set("batch_import_mode",
                          self.batch_import_combo.currentData() or "new_batch")
        self.settings.set("customer_var", self.customer_combo.currentData() or "")
        self.settings.set("variable_order", self.order_combo.currentData() or "smart")
        self.settings.set("show_variable_groups", self.show_groups_checkbox.isChecked())
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
        self.settings.set("validation_enabled", self.validation_checkbox.isChecked())
        self.settings.set("validation_builtin_enabled", self.builtin_validation_checkbox.isChecked())
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

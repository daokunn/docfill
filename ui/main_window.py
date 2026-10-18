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
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QTextEdit, QTextBrowser,
    QHeaderView, QComboBox, QLineEdit, QInputDialog, QAbstractItemView,
    QGroupBox, QFormLayout, QDialog, QDialogButtonBox,
)
from PySide6.QtGui import QShortcut, QKeySequence, QColor

from config.settings import get_settings
from core.scanner import scan_businesses, BusinessInfo, rename_variables_in_template
from core.variable_manager import VariableManager
from core.renderer import render_document, RenderError
from core.alias_mapper import get_alias_mapper
from output.file_output import OutputManager, OutputError
from ui.smart_paste_dialog import SmartPasteDialog
from ui.style import APP_STYLE, TUTORIAL_HTML


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        """初始化主窗口：加载配置、扫描业务、构建 UI"""
        super().__init__()
        self.setWindowTitle("内网离线模板批量填充工具")
        self.resize(1180, 760)
        self.setStyleSheet(APP_STYLE)  # 应用全局现代化浅色主题

        self.settings = get_settings()                     # 全局配置
        self.output_mgr = OutputManager()                   # 输出管理器
        self.businesses: List[BusinessInfo] = []            # 扫描到的业务列表
        self.current_business: Optional[BusinessInfo] = None  # 当前选中的业务
        self.vm: Optional[VariableManager] = None           # 当前业务的变量管理器
        self._last_paste_result: Optional[Dict[str, str]] = None  # 上次智能粘贴结果（数据复用）
        self._last_output_dir: Optional[str] = None         # 上次输出目录（打开目录用）

        self._build_ui()
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
        self.var_table = QTableWidget(0, 4)
        self.var_table.setHorizontalHeaderLabels(["变量名", "值", "必填", "来源"])
        self.var_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # 单击即进入编辑（AllEditTriggers），值列以外的列已在 _refresh_var_table 中设为只读
        self.var_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.var_table.itemChanged.connect(self._on_var_item_changed)
        right_layout.addWidget(self.var_table)

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
        for b in [btn_smart, btn_reuse, btn_norm, btn_add, btn_del, btn_csv]:
            var_btns.addWidget(b)
        var_btns.addStretch()
        right_layout.addLayout(var_btns)

        # 生成按钮（绿色大按钮，样式见 style.py #generate）
        btn_gen = QPushButton("一键生成文档  (Ctrl+G)")
        btn_gen.setObjectName("generate")
        btn_gen.clicked.connect(self._on_generate)
        right_layout.addWidget(btn_gen)

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
        """点击"选择输出根目录"按钮"""
        path = QFileDialog.getExistingDirectory(self, "选择输出根目录")
        if path:
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
        self.vm = VariableManager(business_name=business.name)
        self.vm.init_from_template_vars(sorted(business.variables))
        self._refresh_var_table()
        self._log(f"已加载业务 [{business.name}]，共 {len(self.vm.variables)} 个变量")

    def _refresh_var_table(self) -> None:
        """将 VariableManager 中的变量刷新到表格，空变量高亮显示"""
        self.var_table.blockSignals(True)
        self.var_table.setRowCount(0)
        if not self.vm:
            self.var_table.blockSignals(False)
            return
        for name, var in self.vm.variables.items():
            row = self.var_table.rowCount()
            self.var_table.insertRow(row)
            # 变量名/必填/来源列设为只读，只有"值"列可编辑（配合 AllEditTriggers 单击编辑）
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 0, name_item)
            val_item = QTableWidgetItem(str(var.value))
            # 空变量高亮（柔和浅黄背景）
            if var.value is None or str(var.value).strip() == "":
                val_item.setBackground(QColor("#fef3c7"))
            self.var_table.setItem(row, 1, val_item)
            req_item = QTableWidgetItem("是" if var.required else "否")
            req_item.setFlags(req_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 2, req_item)
            src_item = QTableWidgetItem(var.source)
            src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)
            self.var_table.setItem(row, 3, src_item)
        self.var_table.blockSignals(False)

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

        # 4. 显示将要修改的映射，让用户确认
        mapping_text = "\n".join(f"  {old}  →  {new}" for old, new in name_map.items())
        ret = QMessageBox.question(
            self, "确认统一变量名",
            f"将对当前业务的模板做以下变量名统一：\n\n{mapping_text}\n\n"
            f"此操作会直接修改模板文件，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return

        # 5. 修改模板文件
        total_changed = 0
        for tmpl in self.current_business.templates:
            if tmpl.error:
                continue
            try:
                changed = rename_variables_in_template(tmpl.path, name_map)
                total_changed += changed
                if changed > 0:
                    self._log(f"[统一变量名] {tmpl.name}：修改 {changed} 处")
            except Exception as e:
                self._log(f"[统一变量名] {tmpl.name} 失败：{e}")

        # 6. 重新扫描模板变量并刷新
        self._scan_businesses()
        # 重新选中当前业务
        for i in range(self.biz_list.count()):
            item = self.biz_list.item(i)
            if item.data(Qt.UserRole) == self.current_business.name:
                self.biz_list.setCurrentRow(i)
                break

        self._log(f"统一变量名完成，共修改 {total_changed} 处")
        QMessageBox.information(self, "完成", f"统一变量名完成，共修改 {total_changed} 处")

    def _on_smart_paste(self) -> None:
        """打开智能粘贴对话框，解析结果回填到变量管理器"""
        if not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        # 传入变量名->当前值字典，供对话框判断空变量并排序
        var_dict = {name: var.value for name, var in self.vm.variables.items()}
        dialog = SmartPasteDialog(var_dict, self)
        if not dialog.exec():
            return

        # 多人模式：批量生成文档
        if dialog.multi_results:
            self._batch_generate(dialog.multi_results)
            return

        # 单人模式：回填到变量管理器
        if dialog.result:
            self._last_paste_result = dialog.result  # 缓存供数据复用
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
        """应用上次智能粘贴的数据到当前变量表（数据复用）"""
        if not self._last_paste_result:
            QMessageBox.information(self, "提示", "暂无上次粘贴数据")
            return
        if not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
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
        """批量生成多人文档"""
        if not self.current_business:
            return
        total_success, total_fail = 0, 0
        for i, person_vars in enumerate(people_results, 1):
            # 将每人的变量值回填到变量管理器（合并到现有变量）
            for field, value in person_vars.items():
                if field in self.vm.variables:
                    self.vm.set_value(field, value)
                else:
                    self.vm.add_custom_variable(field, value)
            resolved = self.vm.get_all_resolved()
            name = person_vars.get("姓名") or person_vars.get("客户名") or f"第{i}人"
            self._log(f"\n===== 开始生成第{i}人：{name} =====")
            s, f = self._generate_for_variables(resolved)
            total_success += s
            total_fail += f

        self._log(f"\n批量生成完成：共 {len(people_results)} 人，成功 {total_success} 个，失败 {total_fail} 个")
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
        """从 CSV 文件批量导入变量值（CSV 格式：变量名,值）"""
        if not self.vm:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择CSV文件", "", "CSV文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                csv_text = f.read()
            count = self.vm.load_from_csv(csv_text)
            self._refresh_var_table()
            self._log(f"CSV 导入成功，共 {count} 个变量")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"CSV 导入失败：{e}")

    # ---------- 生成文档 ----------

    def _on_generate(self) -> None:
        """一键生成文档：必填校验 -> 解析变量 -> 渲染模板 -> 输出到业务子文件夹"""
        if not self.current_business or not self.vm:
            QMessageBox.information(self, "提示", "请先选择业务")
            return
        if not self.settings.output_root_dir:
            QMessageBox.information(self, "提示", "请先设置输出根目录")
            return

        # 必填校验
        missing = self.vm.validate()
        if missing:
            ret = QMessageBox.question(
                self, "必填变量缺失",
                f"以下必填变量未填写：{', '.join(missing)}\n\n是否继续生成？",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        resolved = self.vm.get_all_resolved()
        success, fail = self._generate_for_variables(resolved)
        self._log(f"\n生成完成：成功 {success} 个，失败 {fail} 个")
        self._show_generate_result(success, fail)

    def _show_generate_result(self, success: int, fail: int) -> None:
        """显示生成结果，提供打开输出目录按钮"""
        msg = QMessageBox(self)
        msg.setWindowTitle("完成")
        msg.setText(f"生成完成：成功 {success} 个，失败 {fail} 个")
        if self._last_output_dir:
            msg.setInformativeText(f"输出目录：{self._last_output_dir}")
        btn_open = msg.addButton("打开输出目录", QMessageBox.AcceptRole)
        msg.addButton("关闭", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() == btn_open and self._last_output_dir:
            os.startfile(self._last_output_dir)

    def _generate_for_variables(self, resolved: Dict[str, str]) -> Tuple[int, int]:
        """
        根据解析后的变量字典生成当前业务的所有文档。
        :return: (成功数, 失败数)
        """
        try:
            output_dir = self.output_mgr.get_output_dir(self.current_business.name, resolved)
            self._last_output_dir = output_dir  # 记录供打开目录
        except OutputError as e:
            QMessageBox.critical(self, "输出错误", str(e))
            return 0, 0

        logger = self.output_mgr.get_logger(output_dir)
        logger.info(f"===== 开始生成业务：{self.current_business.name} =====")

        success, fail = 0, 0
        for tmpl in self.current_business.templates:
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
                render_document(tmpl.path, out_path, resolved)
                self._log(f"[成功] {tmpl.name} -> {os.path.basename(out_path)}")
                logger.info(f"生成成功：{tmpl.name} -> {out_path}")
                success += 1
            except RenderError as e:
                self._log(f"[失败] {tmpl.name}：{e}")
                logger.error(f"生成失败 {tmpl.name}：{e}")
                fail += 1

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
        """打开设置对话框（目前支持快捷键修改）"""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            # 重新创建快捷键
            for sc in getattr(self, "_shortcuts", []):
                sc.setEnabled(False)
            self._create_shortcuts()
            self._log("设置已更新")

    def _on_tutorial(self) -> None:
        """打开使用教程弹窗（内容见 ui/style.py TUTORIAL_HTML）"""
        TutorialDialog(self).exec()


class TutorialDialog(QDialog):
    """使用教程弹窗：富文本展示操作步骤与常见问题"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用教程")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(TUTORIAL_HTML)
        browser.setOpenExternalLinks(False)
        layout.addWidget(browser)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


class SettingsDialog(QDialog):
    """设置对话框：修改快捷键"""

    SHORTCUT_LABELS = {
        "smart_paste": "智能粘贴解析",
        "generate": "一键生成文档",
        "rescan": "重新扫描模板",
        "reuse": "应用上次数据",
    }

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(400, 300)
        self.settings = settings
        self._shortcut_inputs = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("快捷键设置（格式如 Ctrl+G、F5、Ctrl+Shift+V）："))

        sc = self.settings.get("shortcuts", {})
        form = QFormLayout()
        for key, label in self.SHORTCUT_LABELS.items():
            edit = QLineEdit(sc.get(key, ""))
            edit.setPlaceholderText("留空则禁用")
            self._shortcut_inputs[key] = edit
            form.addRow(f"{label}：", edit)
        layout.addLayout(form)

        layout.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self) -> None:
        """保存快捷键设置"""
        shortcuts = {}
        for key, edit in self._shortcut_inputs.items():
            val = edit.text().strip()
            if val:
                shortcuts[key] = val
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

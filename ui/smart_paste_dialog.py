"""
智能粘贴对话框（PySide6 实现）
功能：
  - 多行文本输入框，用户粘贴原始业务文本
  - 调用 SmartParser 离线解析，表格展示识别结果
  - 支持双击修改值、删除行、新增字段
  - 未识别片段放入"待确认区"，可手动指定归属变量
  - 确认后返回变量字典，由主窗口回填
返回：通过 result 属性获取 {变量名: 值} 字典
"""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidget, QAbstractItemView,
    QInputDialog, QMessageBox, QFrame, QComboBox, QSplitter, QWidget,
)
from PySide6.QtGui import QTextCursor

from core.parser import SmartParser, ParsedField
from core.field_mapper import map_fields_to_template


class SmartTextEdit(QTextEdit):
    """支持粘贴后自动触发解析的文本框"""
    paste_event = Signal()

    def insertFromMimeData(self, source):
        super().insertFromMimeData(source)
        self.paste_event.emit()


class SmartPasteDialog(QDialog):
    """智能粘贴解析对话框"""

    def __init__(self, variable_dict: Dict[str, str], parent=None, business_name: str = ""):
        """
        :param variable_dict: 模板变量字典 {变量名: 当前值}，用于判断空变量并排序
        :param business_name: 当前业务名，用于加载只对该业务生效的用户规则
        """
        super().__init__(parent)
        self.setWindowTitle("智能粘贴解析")
        self.resize(800, 650)

        self.variable_dict = variable_dict            # {变量名: 当前值}
        self.variable_names = list(variable_dict.keys())  # 模板变量名列表
        self.business_name = str(business_name or "")
        self.fields: List[ParsedField] = []           # 当前人的识别结果字段
        # 多人模式：每人的 fields 列表；单人模式为 None
        self.multi_fields: Optional[List[List[ParsedField]]] = None
        # 多人模式：每人的未识别片段（与 multi_fields 一一对应，切人时同步显示）
        self.multi_unrecognized: Optional[List[List[str]]] = None
        self.result: Optional[Dict[str, str]] = None  # 单人确认结果
        self.multi_results: Optional[List[Dict[str, str]]] = None  # 多人确认结果
        self._last_parser: Optional[SmartParser] = None  # 保留解析器，供规则配置提示使用

        self._build_ui()

    def _build_ui(self) -> None:
        """构建对话框 UI：文本输入区、解析结果表格、待确认区、操作按钮。

        输入区与结果表之间用可拖动分隔条连接，变量多/资料长时能拉大输入区看全；
        分隔位置保存到本机设置，下次打开沿用。
        """
        from config.settings import get_settings
        self._settings = get_settings()

        layout = QVBoxLayout(self)

        # 上半部分：输入区
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(QLabel("请将数据粘贴到下方（多人数据用 --- 或 === 分隔，独占一行）："))
        self.text_input = SmartTextEdit()
        self.text_input.setMinimumHeight(80)
        self.text_input.paste_event.connect(self._on_parse)  # 粘贴后自动解析
        top_layout.addWidget(self.text_input, 1)

        btn_parse = QPushButton("智能解析")
        btn_parse.clicked.connect(self._on_parse)
        top_layout.addWidget(btn_parse, alignment=Qt.AlignCenter)

        self.multi_selector = QComboBox()
        self.multi_selector.currentIndexChanged.connect(self._on_switch_person)
        self.multi_selector.setVisible(False)
        top_layout.addWidget(self.multi_selector)

        # 下半部分：结果表格
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(QLabel("解析结果："))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["变量名", "识别值", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_edit_value)
        bottom_layout.addWidget(self.table, 1)

        self.coverage_label = QLabel("")
        self.coverage_label.setWordWrap(True)
        self.coverage_label.setStyleSheet("color: #6b7280;")
        bottom_layout.addWidget(self.coverage_label)

        # 可拖动分隔条：输入区 ↔ 结果区
        self.splitter = QSplitter(Qt.Vertical, self)
        self.splitter.addWidget(top)
        self.splitter.addWidget(bottom_widget)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 4)
        self.splitter.setChildrenCollapsible(False)
        saved_sizes = self._settings.get("smart_paste_splitter", [])
        if isinstance(saved_sizes, list) and len(saved_sizes) == 2:
            try:
                self.splitter.setSizes([int(saved_sizes[0]), int(saved_sizes[1])])
            except (TypeError, ValueError):
                pass
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        layout.addWidget(self.splitter, 1)

        # 操作按钮
        op_layout = QHBoxLayout()
        for text, slot in [("修改选中值", self._on_edit_value),
                           ("删除选中", self._on_delete),
                           ("新增字段", self._on_add)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            op_layout.addWidget(btn)
        self.btn_rules = QPushButton("配置识别规则…")
        self.btn_rules.setToolTip(
            "为规则库里没有的变量写识别正则。\n"
            "模板变量名保持 {{变量名}} 不变，规则单独保存，升级不丢失。")
        self.btn_rules.clicked.connect(self._on_edit_rules)
        op_layout.addWidget(self.btn_rules)
        op_layout.addStretch()
        layout.addLayout(op_layout)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        # 未识别区：用大白话说明用途，避免用户以为这些片段非填不可
        self.lbl_unrec_hint = QLabel(
            "看不懂的零碎信息放在这里。这些可有可无——不用管也能正常生成，"
            "只有当你确认某条正好是某个空变量的值时，才需要赋值给它。")
        self.lbl_unrec_hint.setWordWrap(True)
        self.lbl_unrec_hint.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(self.lbl_unrec_hint)
        self.unrec_list = QListWidget()
        self.unrec_list.setFixedHeight(80)
        self.unrec_list.itemDoubleClicked.connect(lambda: self._on_assign_unrec())
        layout.addWidget(self.unrec_list)
        unrec_btn_layout = QHBoxLayout()
        btn_assign = QPushButton("赋值给空变量...")
        btn_assign.setToolTip("只有确认片段是某个空变量的值时才用；可双击片段直接赋值。")
        btn_assign.clicked.connect(self._on_assign_unrec)
        btn_ignore = QPushButton("全部忽略（不影响生成）")
        btn_ignore.setToolTip("清空这一区。这些片段不会写进文档，你可以放心生成。")
        btn_ignore.clicked.connect(self._on_ignore_unrec)
        unrec_btn_layout.addWidget(btn_assign)
        unrec_btn_layout.addWidget(btn_ignore)
        layout.addLayout(unrec_btn_layout)

        # 底部
        bottom = QHBoxLayout()
        self.lbl_count = QLabel("")
        bottom.addWidget(self.lbl_count)
        bottom.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("确认填充")
        btn_ok.clicked.connect(self._on_confirm)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_ok)
        layout.addLayout(bottom)

    def _on_splitter_moved(self, *args) -> None:
        """记住拖动后的分隔位置（节流：只在变化时写）。"""
        sizes = self.splitter.sizes()
        if len(sizes) == 2 and sizes != self._settings.get("smart_paste_splitter", []):
            self._settings.set("smart_paste_splitter", [int(sizes[0]), int(sizes[1])])

    def _on_parse(self) -> None:
        """点击"智能解析"按钮：调用 SmartParser 离线解析并填充结果表格"""
        text = self.text_input.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "提示", "请先粘贴文本")
            return

        parser = SmartParser(business_name=self.business_name)
        self._last_parser = parser
        # 检测是否多人数据
        blocks = parser.split_multi(text)
        if len(blocks) > 1:
            # 多人模式
            results = parser.parse_multi(text)
            self.multi_fields = [
                map_fields_to_template(result.fields, self.variable_names)
                for result in results
            ]
            # 同步保存每人的未识别片段，切人时在待确认区显示（以前被直接丢弃）
            self.multi_unrecognized = [list(result.unrecognized) for result in results]
            self.multi_selector.setVisible(True)
            self.multi_selector.blockSignals(True)
            self.multi_selector.clear()
            for i, fields in enumerate(self.multi_fields):
                # 尝试用姓名/客户名作为显示
                name = next((f.value for f in fields if f.field in ("姓名", "客户名")), f"第{i+1}人")
                self.multi_selector.addItem(f"第{i+1}人 - {name}")
            self.multi_selector.blockSignals(False)
            self.multi_selector.setCurrentIndex(0)
            self._on_switch_person(0)
        else:
            # 单人模式
            self.multi_fields = None
            self.multi_unrecognized = None
            self.multi_selector.setVisible(False)
            result = parser.parse(text)
            self.fields = map_fields_to_template(result.fields, self.variable_names)
            self._refresh_table(self.fields, result.unrecognized)
            self.lbl_count.setText(self._count_text(self.fields))
        self._show_rule_errors(parser)

    def _on_switch_person(self, index: int) -> None:
        """多人模式下切换查看某人的解析结果"""
        if self.multi_fields is None or index < 0 or index >= len(self.multi_fields):
            return
        self.fields = self.multi_fields[index]
        # 显示该人的未识别片段（不再丢弃），赋值后也能写回对应的人
        unrec = (self.multi_unrecognized[index]
                 if self.multi_unrecognized and index < len(self.multi_unrecognized) else [])
        self._refresh_table(self.fields, unrec)
        self.lbl_count.setText(f"第{index+1}人：{self._count_text(self.fields)}（共{len(self.multi_fields)}人）")

    def _refresh_table(self, fields: List[ParsedField], unrecognized: List[str]) -> None:
        """刷新结果表格和待确认区"""
        self.table.setRowCount(0)
        for f in fields:
            self._append_row(f)
        self.unrec_list.clear()
        for u in unrecognized:
            self.unrec_list.addItem(u)
        self._refresh_coverage()

    def _refresh_coverage(self) -> None:
        """显示模板变量的填充覆盖情况：已匹配/待填写/未使用。"""
        present = {field.field for field in self.fields if field.in_template}
        missing = [name for name in self.variable_names if name not in present]
        extras = [
            field.field for field in self.fields
            if not field.in_template and field.source != "manual"
        ]

        parts = [f"模板覆盖：{len(present)}/{len(self.variable_names)}"]
        if missing:
            shown = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
            parts.append(f"待填写：{shown}")
        if extras:
            shown = "、".join(extras[:5]) + ("…" if len(extras) > 5 else "")
            parts.append(f"未使用：{shown}")
        self.coverage_label.setText("；".join(parts))

    @staticmethod
    def _count_text(fields: List[ParsedField]) -> str:
        """生成“识别/匹配/未使用”摘要。"""
        matched = sum(1 for f in fields if f.in_template)
        unused = len(fields) - matched
        if unused:
            return f"识别 {len(fields)} 个字段，匹配模板 {matched} 个，未使用 {unused} 个"
        return f"识别 {len(fields)} 个字段，全部匹配模板"

    def _append_row(self, f: ParsedField) -> None:
        """向结果表格追加一行识别字段"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(f.field)
        if f.mapped_from:
            name_item.setToolTip(f"由识别字段「{f.mapped_from}」自动匹配")
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem(f.value))

        if f.conflict:
            status = "冲突"
        elif f.source == "manual":
            status = "手动添加"
        elif not f.in_template:
            status = "模板中无"
        elif f.mapped_from:
            status = "已自动匹配"
        else:
            status = "已识别"

        status_item = QTableWidgetItem(status)
        if f.mapped_from:
            status_item.setToolTip(f"已匹配到模板变量「{f.field}」")
        self.table.setItem(row, 2, status_item)

    def _on_edit_value(self) -> None:
        """双击或点击"修改选中值"：手动编辑识别值"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一行")
            return
        field = self.fields[row]
        new_val, ok = QInputDialog.getText(
            self, "修改值", f"变量 [{field.field}] 的值：", text=field.value)
        if ok:
            field.value = new_val
            field.conflict = False
            self.table.setItem(row, 1, QTableWidgetItem(new_val))
            self.table.setItem(row, 2, QTableWidgetItem("已修改"))

    def _on_delete(self) -> None:
        """删除选中的识别字段行"""
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        del self.fields[row]
        self._refresh_coverage()

    def _on_add(self) -> None:
        """手动新增一个识别字段（下拉框选择变量名，空变量优先）"""
        items = self._get_sorted_var_items()
        if not items:
            field_name, ok = QInputDialog.getText(self, "新增字段", "请输入变量名：")
            if not ok or not field_name.strip():
                return
        else:
            var_display, ok = QInputDialog.getItem(
                self, "新增字段", "请选择或输入变量名：\n（⭐为空变量，优先选择）",
                items, 0, True)
            if not ok or not var_display.strip():
                return
            field_name = self._extract_var_name(var_display)
            if not field_name:
                return

        value, ok2 = QInputDialog.getText(self, "新增字段", f"请输入 [{field_name}] 的值：")
        if not ok2:
            return
        pf = ParsedField(field=field_name, value=value,
                         label=field_name, source="manual")
        pf.in_template = field_name in self.variable_names
        self.fields.append(pf)
        self._append_row(pf)
        self._refresh_coverage()

    def _get_sorted_var_items(self) -> List[str]:
        """
        生成排序后的变量名列表：空变量排在前面（标⭐），已有值的排在后面。
        用于下拉框快速选择。
        """
        empty_vars = []
        filled_vars = []
        for name in self.variable_names:
            val = self.variable_dict.get(name, "")
            if val is None or str(val).strip() == "":
                empty_vars.append(name)
            else:
                filled_vars.append(name)
        # 空变量标⭐优先，已有值的标(已有值)
        return [f"⭐ {n}" for n in empty_vars] + [f"{n}（已有值）" for n in filled_vars]

    def _get_unrec_var_items(self) -> List[str]:
        """待确认区赋值专用的下拉项：只列空变量。

        用户反馈的核心困惑就是"下拉里大部分变量都已填充，不知道在干什么"。
        这里只列没填的变量，赋值意图一目了然；如需覆盖已填变量，仍可在
        下拉里手动输入变量名（QInputDialog.getItem 的 editable 模式）。
        """
        return [f"⭐ {n}" for n in self.variable_names
                if str(self.variable_dict.get(n, "") or "").strip() == ""]

    def _extract_var_name(self, display: str) -> str:
        """从下拉框显示文本中提取纯变量名（去掉 ⭐ 和（已有值）标记）"""
        name = display.strip()
        if name.startswith("⭐"):
            name = name[1:].strip()
        if name.endswith("（已有值）"):
            name = name[:-5].strip()
        return name

    def _on_ignore_unrec(self) -> None:
        """一键忽略待确认区全部片段：只是不显示、不写入，不影响生成。"""
        self.unrec_list.clear()
        self._sync_unrecognized_back()

    def _on_assign_unrec(self) -> None:
        """将待确认区选中的未识别片段赋值给变量（下拉框选择，空变量优先）"""
        item = self.unrec_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在待确认区选中一个片段")
            return
        fragment = item.text()

        # 只列空变量，避免"大部分变量都已填充，不知道在干什么"的困惑
        items = self._get_unrec_var_items()
        prompt = (f"这个片段是：[{fragment}]\n\n"
                  "如果它正好是某个还没填的变量的值，选它；否则点【取消】忽略。")
        if items:
            var_display, ok = QInputDialog.getItem(
                self, "赋值给空变量", prompt + "\n（如需覆盖已填变量，可直接输入变量名）",
                items, 0, True)  # editable=True 允许手动输入覆盖已填变量
            if ok and var_display.strip():
                var_name = self._extract_var_name(var_display)
                if var_name:
                    self._add_manual_field(var_name, fragment, item)
        else:
            # 没有空变量，退化为手动输入
            var_name, ok = QInputDialog.getText(self, "赋值给变量", prompt)
            if ok and var_name.strip():
                self._add_manual_field(var_name.strip(), fragment, item)

    def _add_manual_field(self, field_name: str, value: str, source_item=None) -> None:
        """新增一个手动赋值的字段，并从待确认区移除对应片段"""
        pf = ParsedField(field=field_name, value=value,
                         label=field_name, source="manual")
        pf.in_template = field_name in self.variable_names
        self.fields.append(pf)
        self._append_row(pf)
        self._refresh_coverage()
        if source_item is not None:
            self.unrec_list.takeItem(self.unrec_list.row(source_item))
            self._sync_unrecognized_back()

    def _sync_unrecognized_back(self) -> None:
        """把待确认区当前内容写回当前人的 multi_unrecognized，切人后不丢失。"""
        if self.multi_unrecognized is None or self.multi_selector.currentIndex() < 0:
            return
        idx = self.multi_selector.currentIndex()
        if idx < len(self.multi_unrecognized):
            self.multi_unrecognized[idx] = [
                self.unrec_list.item(i).text() for i in range(self.unrec_list.count())]

    def _show_rule_errors(self, parser: SmartParser) -> None:
        """把无法编译的规则显示出来。

        以前非法正则是静默丢弃的，用户写完以为生效了其实没有，
        这里显式提示，避免排查半天找不到原因。
        """
        if parser.rule_errors:
            QMessageBox.warning(
                self, "部分识别规则无法生效",
                "以下规则的正则写法有误，本次解析已跳过：\n\n"
                + "\n".join(parser.rule_errors[:6]))

    def _unmatched_template_vars(self) -> List[str]:
        """模板里有、但本次没被任何识别结果覆盖的变量名。"""
        covered = {f.field for f in self.fields if f.in_template}
        return [name for name in self.variable_names if name not in covered]

    def _on_edit_rules(self) -> None:
        """打开规则编辑对话框，为新变量配置识别正则。

        默认选中第一个未匹配的模板变量，并把待确认区的片段作为测试样本带过去，
        这样用户是"指着真实数据配规则"，不用凭空想象该变量长什么样。
        """
        from ui.rule_editor_dialog import RuleEditorDialog

        unmatched = self._unmatched_template_vars()
        target = unmatched[0] if unmatched else ""

        samples = [self.unrec_list.item(i).text()
                   for i in range(self.unrec_list.count())]

        dialog = RuleEditorDialog(
            business_name=self.business_name,
            template_vars=self.variable_names,
            target_var=target,
            seed_samples=samples,
            probe_text=self.text_input.toPlainText(),
            parent=self,
        )
        dialog.exec()

        if not dialog.saved:
            return

        # 规则库变了，用新规则重新解析一遍当前文本
        text = self.text_input.toPlainText()
        if text.strip():
            self._on_parse()
            QMessageBox.information(
                self, "已应用新规则",
                "已按新规则重新解析。请核对下方结果是否符合预期。")

    @staticmethod
    def _usable_fields(fields: List[ParsedField]) -> List[ParsedField]:
        """只返回会写入模板的字段：匹配到模板的 + 用户手动新增的。"""
        return [f for f in fields if f.in_template or f.source == "manual"]

    def _on_confirm(self) -> None:
        """确认填充：单人返回 dict，多人返回 list[dict]"""
        if self.multi_fields is not None:
            # 多人模式
            self.multi_results = [
                {f.field: f.value for f in self._usable_fields(fields)}
                for fields in self.multi_fields
                if self._usable_fields(fields)
            ]
            if not self.multi_results:
                QMessageBox.information(self, "提示", "没有匹配到模板变量，请先检查模板或手动新增字段")
                return
            self.result = self.multi_results[0]  # 兼容单人 result 属性
            self.accept()
        else:
            # 单人模式
            usable = self._usable_fields(self.fields)
            if not usable:
                QMessageBox.information(self, "提示", "没有匹配到模板变量，请先检查模板或手动新增字段")
                return
            # 拦截"大片待填写"：模板变量多但只匹配少数时，先让用户确认，
            # 避免 20 个变量只填 3 个就一路生成、打印后才发现空白。
            missing = self._unmatched_template_vars()
            from core.preflight import should_warn_incomplete_paste
            if should_warn_incomplete_paste(len(usable), len(self.variable_names)):
                shown = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
                reply = QMessageBox.warning(
                    self, "还有变量没填",
                    f"模板共 {len(self.variable_names)} 个变量，本次只填入 {len(usable)} 个。\n"
                    f"仍未填写：{shown}\n\n"
                    "这些位置生成后会是空白。要继续吗？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return
            self.result = {f.field: f.value for f in usable}
            self.accept()

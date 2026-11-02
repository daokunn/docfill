"""变量默认值与计算：一个简洁的统一配置窗口。

左侧选变量，右侧只填三件事：
  1. 这个变量是手动填、默认值，还是公式算
  2. 默认值/公式写什么
  3. 小数位、作用范围、名单空白时是否套用、是否写入汇总

辅助变量（模板里没有、只用于计算/汇总）也在这里新增。
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core.expression import evaluate, ExpressionError
from core.variable_rules import (
    BUSINESS_SCOPE, GLOBAL_SCOPE, load_document, merged_rules, remove_rule,
    set_rule,
)
from core.variable_manager import round_half_up

MODE_LABELS = [
    ("手动填写", "manual"),
    ("默认值（空白时自动填，可改）", "default"),
    ("公式计算（自动算，只读）", "formula"),
]


class VariableRulesDialog(QDialog):
    """管理某个业务的默认值、公式和辅助变量。"""

    def __init__(self, business_name: str, template_vars: List[str],
                 current_values: Optional[Dict[str, Any]] = None,
                 legacy_defaults: Optional[Dict[str, str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"变量默认值与计算 · {business_name or '未选择业务'}")
        self.resize(900, 620)
        self.business_name = business_name
        self.template_vars = [str(v) for v in template_vars if str(v).strip()]
        self.current_values = dict(current_values or {})
        self.document = load_document()
        self.old_rules = merged_rules(business_name, self.document)
        self.rules: Dict[str, Dict[str, Any]] = {}
        for name, rule in self.old_rules.items():
            self.rules[name] = dict(rule)
        # 把旧 defaults.json 里的默认值显示出来，用户保存后转成新规则
        for name, expr in (legacy_defaults or {}).items():
            if name not in self.rules and str(expr or "").strip():
                self.rules[name] = {
                    "mode": "default", "expr": str(expr), "decimals": 0,
                    "apply_on_empty": True, "export_summary": False,
                    "kind": "template", "allow_override": False,
                    "_scope": BUSINESS_SCOPE,
                }
        self.names: List[str] = []
        for name in self.template_vars + sorted(self.rules):
            if name and name not in self.names:
                self.names.append(name)
        self.changed = False
        self._editing_name = ""
        self._build_ui()
        self._load_list()
        if self.names:
            self.var_list.setCurrentRow(0)
            self._load_rule(self.names[0])

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("先选择一个变量："))
        self.var_list = QListWidget()
        self.var_list.currentTextChanged.connect(self._on_select)
        left.addWidget(self.var_list, 1)
        add_btn = QPushButton("新增辅助变量…")
        add_btn.setToolTip("模板里没有、但计算或汇总要用的变量，例如“期限月数”")
        add_btn.clicked.connect(self._on_add_aux)
        left.addWidget(add_btn)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.kind_label = QLabel("")
        form.addRow("用在哪里：", self.kind_label)
        self.mode_combo = QComboBox()
        for label, value in MODE_LABELS:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("怎么得到值：", self.mode_combo)
        self.expr_edit = QLineEdit()
        self.expr_edit.setPlaceholderText("默认值：某某公司、today()；公式：本金 + 利息")
        form.addRow("默认值或公式：", self.expr_edit)
        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 6)
        self.decimals_spin.setToolTip("数值结果保留几位小数；0 = 整数，2 = 保留两位")
        form.addRow("保留小数位：", self.decimals_spin)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("只用于这个业务", BUSINESS_SCOPE)
        self.scope_combo.addItem("所有业务通用", GLOBAL_SCOPE)
        form.addRow("作用范围：", self.scope_combo)
        self.apply_checkbox = QCheckBox("名单里这一格空着时，自动填默认值")
        form.addRow("", self.apply_checkbox)
        self.export_checkbox = QCheckBox("也写入移交清单 / 汇总表")
        form.addRow("", self.export_checkbox)
        self.override_checkbox = QCheckBox("允许手动修改公式算出的结果")
        form.addRow("", self.override_checkbox)
        remove_row = QHBoxLayout()
        remove_btn = QPushButton("删除这个变量的规则")
        remove_btn.setToolTip("恢复成手动填写；不会删除模板里的变量本身")
        remove_btn.clicked.connect(self._on_remove_rule)
        remove_row.addWidget(remove_btn)
        remove_row.addStretch()
        form.addRow("", remove_row)
        right.addLayout(form)

        right.addWidget(QLabel("可用变量（双击插入到公式）："))
        self.var_picker = QListWidget()
        self.var_picker.setMaximumHeight(150)
        for name in self.names:
            self.var_picker.addItem(name)
        self.var_picker.itemDoubleClicked.connect(self._insert_variable)
        right.addWidget(self.var_picker)

        test_row = QHBoxLayout()
        test_btn = QPushButton("用当前值试算")
        test_btn.setToolTip("拿当前已填的值运行这条公式，看看结果对不对")
        test_btn.clicked.connect(self._on_test)
        self.test_label = QLabel("")
        self.test_label.setWordWrap(True)
        self.test_label.setStyleSheet("color:#2563eb;")
        test_row.addWidget(test_btn)
        test_row.addWidget(self.test_label, 1)
        right.addLayout(test_row)

        self.hint = QLabel(
            "公式支持四则运算、括号和 Python 切片：身份证号[6:14]、手机号[-4:]；"
            "文本拼接用 concat(姓, 名)。数值请直接写变量名，结果按小数位四舍五入。\n"
            "可选项没填时会在 + - * 里自动忽略，A=B+C+D+E 不会因为 E 为空而报错。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#6b7280; font-size:9pt;")
        right.addWidget(self.hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        right.addWidget(btns)
        layout.addLayout(right, 2)

    def _load_list(self) -> None:
        self.var_list.blockSignals(True)
        self.var_list.clear()
        for name in self.names:
            rule = self.rules.get(name) or {}
            suffix = "（辅助）" if rule.get("kind") == "aux" else ""
            self.var_list.addItem(QListWidgetItem(f"{name}{suffix}"))
        self.var_list.blockSignals(False)

    def _current_name(self) -> str:
        item = self.var_list.currentItem()
        if not item:
            return ""
        text = item.text()
        return text.replace("（辅助）", "").strip()

    def _on_select(self, _text: str) -> None:
        name = self._current_name()
        # 先把上一个变量的修改收进草稿，再切换，避免切走就丢
        if self._editing_name and self._editing_name != name:
            self.rules[self._editing_name] = self._collect_for(self._editing_name)
        if name:
            self._load_rule(name)

    def _load_rule(self, name: str) -> None:
        self._editing_name = name
        rule = self.rules.get(name) or {}
        self.kind_label.setText("辅助变量（模板里没有）" if rule.get("kind") == "aux"
                                else "模板变量")
        mode = str(rule.get("mode") or "manual")
        index = self.mode_combo.findData(mode)
        self.mode_combo.setCurrentIndex(max(index, 0))
        self.expr_edit.setText(str(rule.get("expr") or ""))
        self.decimals_spin.setValue(int(rule.get("decimals", 0) or 0))
        scope = str(rule.get("_scope") or BUSINESS_SCOPE)
        self.scope_combo.setCurrentIndex(max(self.scope_combo.findData(scope), 0))
        self.apply_checkbox.setChecked(bool(rule.get("apply_on_empty", True)))
        self.export_checkbox.setChecked(bool(rule.get("export_summary", False)))
        self.override_checkbox.setChecked(bool(rule.get("allow_override", False)))
        self.test_label.setText("")
        self._sync_mode()

    def _sync_mode(self) -> None:
        mode = self.mode_combo.currentData()
        is_formula = mode == "formula"
        self.decimals_spin.setEnabled(is_formula)
        self.override_checkbox.setEnabled(is_formula)
        self.apply_checkbox.setEnabled(mode == "default")
        self.expr_edit.setEnabled(mode != "manual")

    def _collect_current(self) -> Dict[str, Any]:
        return self._collect_for(self._current_name())

    def _expr_text(self, name: str) -> str:
        """允许用户直接写 A=B+C，自动去掉开头的“变量名=”。"""
        text = self.expr_edit.text().strip()
        if "=" in text:
            left, right = text.split("=", 1)
            if left.strip() == name:
                return right.strip()
        return text

    def _collect_for(self, name: str) -> Dict[str, Any]:
        mode = self.mode_combo.currentData() or "manual"
        rule = dict(self.rules.get(name) or {})
        rule.update({
            "mode": mode,
            "expr": self._expr_text(name),
            "decimals": int(self.decimals_spin.value()),
            "apply_on_empty": self.apply_checkbox.isChecked(),
            "export_summary": self.export_checkbox.isChecked(),
            "allow_override": self.override_checkbox.isChecked(),
            "kind": "aux" if rule.get("kind") == "aux" else "template",
            "_scope": self.scope_combo.currentData() or BUSINESS_SCOPE,
        })
        return rule

    def _insert_variable(self, item: QListWidgetItem) -> None:
        if not self.expr_edit.isEnabled():
            return
        self.expr_edit.insert(item.text())

    def _on_test(self) -> None:
        expr = self._expr_text(self._current_name())
        if not expr:
            self.test_label.setText("先填写默认值或公式")
            return
        context = dict(self.current_values)
        # 允许测试时引用其他变量的当前值；计算变量本身不参与
        try:
            result = evaluate(expr, context)
        except ExpressionError:
            # 默认值允许写普通文本
            if self.mode_combo.currentData() == "default":
                self.test_label.setText(f"作为文本使用：{expr}")
            else:
                self.test_label.setText("公式有误，请检查变量名/语法")
            return
        result = round_half_up(result, int(self.decimals_spin.value()))
        self.test_label.setText(f"试算结果：{result}")

    def _on_remove_rule(self) -> None:
        name = self._current_name()
        if not name:
            return
        if name not in self.template_vars and name in self.names:
            self.rules.pop(name, None)
            self.names.remove(name)
            self._load_list()
            if self.names:
                self.var_list.setCurrentRow(0)
                self._load_rule(self.names[0])
            for row in range(self.var_picker.count() - 1, -1, -1):
                if self.var_picker.item(row).text() == name:
                    self.var_picker.takeItem(row)
        else:
            # 模板变量保留一行“手动”，用于覆盖旧 defaults.json 的默认值
            self.rules[name] = {
                "mode": "manual", "expr": "", "decimals": 0,
                "apply_on_empty": True, "export_summary": False,
                "kind": "template", "allow_override": False,
                "_scope": BUSINESS_SCOPE, "_legacy_clear": True,
            }
            self._load_rule(name)
            self.test_label.setText("已清除该变量的规则")

    def _on_add_aux(self) -> None:
        self._save_current()
        name, ok = QInputDialog.getText(self, "新增辅助变量", "变量名（用于公式/汇总）：")
        name = name.strip()
        if not ok or not name:
            return
        if not name.isidentifier():
            QMessageBox.warning(self, "变量名不可用",
                                "辅助变量名要能写进公式，只能使用中文/字母/数字/下划线，"
                                "且不能有空格或以数字开头。")
            return
        if name in self.names:
            QMessageBox.information(self, "提示", "这个变量已经存在。")
            return
        self.rules[name] = {
            "mode": "formula", "expr": "", "decimals": 0,
            "apply_on_empty": False, "export_summary": True,
            "kind": "aux", "allow_override": False, "_scope": BUSINESS_SCOPE,
        }
        self.names.append(name)
        self._load_list()
        self.var_picker.addItem(name)
        self.var_list.setCurrentRow(self.names.index(name))
        self._load_rule(name)

    def _save_current(self) -> None:
        name = self._editing_name or self._current_name()
        if name:
            self.rules[name] = self._collect_for(name)

    def _on_accept(self) -> None:
        self._save_current()
        # 先删除当前业务已不存在的旧规则
        for name in list(self.old_rules):
            if name not in self.rules:
                old_scope = self.old_rules[name].get("_scope") or BUSINESS_SCOPE
                remove_rule(self.business_name, name, old_scope, self.document)
                self.changed = True
        for name, rule in self.rules.items():
            mode = str(rule.get("mode") or "manual")
            scope = str(rule.get("_scope") or BUSINESS_SCOPE)
            old_scope = (self.old_rules.get(name) or {}).get("_scope")
            if mode == "manual" and rule.get("kind") != "aux" and not rule.get("_legacy_clear"):
                if old_scope:
                    remove_rule(self.business_name, name, old_scope, self.document)
                continue
            clean = {key: value for key, value in rule.items() if not key.startswith("_")}
            set_rule(self.business_name, name, clean, scope, self.document)
            self.changed = True
        self.accept()

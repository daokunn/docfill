"""变量校验规则配置窗口。

与「变量默认值与计算」「识别规则」保持一致的体验：
左侧选变量，右侧选校验方式（内置预设或自定义正则），可设全局/仅本业务。
默认带几个常见变量的内置预设，用户可为任意变量补自定义规则。
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from core.validator import (
    PRESET_LABELS, normalize_rule, load_document, merged_rules, remove_rule, default_rule_for_variable,
    save_document, set_rule, validate_value,
)


class ValidationRulesDialog(QDialog):
    """管理生成前的变量校验规则。"""

    def __init__(self, business_name: str, template_vars: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("变量校验规则")
        self.resize(780, 560)
        self.business_name = str(business_name or "")
        self.template_vars = [str(v) for v in template_vars if str(v).strip()]
        self.document = load_document()
        self.rules: Dict[str, Dict[str, Any]] = {
            name: dict(rule)
            for name, rule in merged_rules(self.document, self.business_name).items()
        }
        self.names: List[str] = []
        for name in self.template_vars + sorted(self.rules):
            if name and name not in self.names:
                self.names.append(name)
        self._editing = False
        self._build_ui()
        if self.names:
            self.var_list.setCurrentRow(0)
            self._load_rule(self.names[0])

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("选择一个变量："))
        self.var_list = QListWidget()
        self.var_list.currentTextChanged.connect(self._on_select)
        left.addWidget(self.var_list, 1)
        add_btn = QPushButton("新增变量…")
        add_btn.setToolTip("模板里没有、但要校验的变量也可新增")
        add_btn.clicked.connect(self._on_add)
        left.addWidget(add_btn)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("所有业务（全局）", "global")
        self.scope_combo.addItem(f"仅「{self.business_name or '当前业务'}」", "business")
        form.addRow("作用范围：", self.scope_combo)
        form.addRow("校验方式：", self._preset_combo())
        self.regex_edit = QLineEdit()
        self.regex_edit.setPlaceholderText(r"例如 ^[\u4e00-\u9fa5]{2,4}$")
        form.addRow("自定义正则：", self.regex_edit)
        self.message_edit = QLineEdit()
        self.message_edit.setPlaceholderText("留空=用默认提示，例如“身份证号不合法”")
        form.addRow("出错提示：", self.message_edit)
        self.enabled_check = QCheckBox("启用这条校验")
        self.enabled_check.setChecked(True)
        form.addRow("", self.enabled_check)
        right.addLayout(form)

        test_row = QHBoxLayout()
        test_row.addWidget(QLabel("试一下："))
        self.test_edit = QLineEdit()
        self.test_edit.setPlaceholderText("填个样例值，点“测试”看会不会报错")
        test_row.addWidget(self.test_edit, 1)
        btn_test = QPushButton("测试")
        btn_test.clicked.connect(self._on_test)
        test_row.addWidget(btn_test)
        right.addLayout(test_row)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        right.addWidget(self.test_result)

        tip = QLabel(
            "内置预设开箱即用；其他变量选“自定义正则”自己写。\n"
            "留空的值不会被校验（仍由生成前的空变量检查负责）。规则存本机，升级不覆盖。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#6b7280; font-size:9pt;")
        right.addWidget(tip)

        right.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        btn_remove = QPushButton("删除此规则")
        btn_remove.clicked.connect(self._on_remove)
        row.addWidget(btn_remove)
        right.addLayout(row)
        layout.addLayout(right, 2)

        outer = QVBoxLayout(self)
        outer.addLayout(layout, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _preset_combo(self):
        self.preset_combo = QComboBox()
        for label, value in PRESET_LABELS.items():
            self.preset_combo.addItem(label, value)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        return self.preset_combo

    def _load_list(self) -> None:
        current = self.var_list.currentRow()
        self.var_list.clear()
        for name in self.names:
            rule = self.rules.get(name)
            mark = "✓" if rule and rule.get("enabled") else "·"
            self.var_list.addItem(f"{mark} {name}")
        if 0 <= current < self.var_list.count():
            self.var_list.setCurrentRow(current)

    def _on_select(self, display: str) -> None:
        name = self._name_from_display(display)
        if name:
            self._editing = True
            try:
                self._load_rule(name)
            finally:
                self._editing = False

    @staticmethod
    def _name_from_display(display: str) -> str:
        return str(display or "")[2:].strip() if len(str(display or "")) > 2 else ""

    def _load_rule(self, name: str) -> None:
        rule = self.rules.get(name, {})
        scope = rule.get("_scope", "global")
        idx = self.scope_combo.findData(scope)
        self.scope_combo.setCurrentIndex(max(idx, 0))
        preset = rule.get("preset", "custom")
        idx = self.preset_combo.findData(preset)
        self.preset_combo.setCurrentIndex(max(idx, 0))
        self.regex_edit.setText(str(rule.get("regex", "") or ""))
        self.message_edit.setText(str(rule.get("message", "") or ""))
        self.enabled_check.setChecked(bool(rule.get("enabled", True)))
        self._on_preset_changed()
        self.test_result.setText("")

    def _on_preset_changed(self) -> None:
        is_custom = self.preset_combo.currentData() == "custom"
        self.regex_edit.setEnabled(is_custom)

    def _collect_current(self) -> Optional[tuple]:
        name = self._name_from_display(self.var_list.currentItem().text()) if self.var_list.currentItem() else ""
        if not name:
            return None
        rule = {
            "preset": self.preset_combo.currentData() or "custom",
            "regex": self.regex_edit.text().strip(),
            "message": self.message_edit.text().strip(),
            "enabled": self.enabled_check.isChecked(),
        }
        return name, rule, self.scope_combo.currentData() or "global"

    def _on_test(self) -> None:
        collected = self._collect_current()
        if not collected:
            return
        _, rule, _ = collected
        value = self.test_edit.text()
        error = validate_value(value, rule)
        if error:
            self.test_result.setText(f"✗ 会报错：{error}")
            self.test_result.setStyleSheet("color:#b91c1c;")
        else:
            self.test_result.setText("✓ 通过（不会被拦截）" if value.strip() else "空值会被跳过")
            self.test_result.setStyleSheet("color:#15803d;")

    def _on_add(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "新增变量", "要校验的变量名：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name not in self.names:
            self.names.append(name)
        from core.validator import default_rule_for_variable
        builtin = default_rule_for_variable(name)
        self.rules[name] = builtin if builtin else normalize_rule({"preset": "custom"})
        self._load_list()
        self.var_list.setCurrentRow(self.names.index(name))
        self._load_rule(name)

    def _on_remove(self) -> None:
        collected = self._collect_current()
        if not collected:
            return
        name, _, scope = collected
        self.rules.pop(name, None)
        remove_rule(self.document, name, scope=scope, business_name=self.business_name)
        self._load_list()

    def _on_accept(self) -> None:
        # 保存当前正在编辑的一条
        if self.var_list.currentItem():
            collected = self._collect_current()
            if collected:
                name, rule, scope = collected
                self.rules[name] = {**rule, "_scope": scope}
        for name, rule in self.rules.items():
            if rule.get("preset") == "custom" and not str(rule.get("regex", "")).strip():
                QMessageBox.warning(self, "规则不完整", f"变量「{name}」选了自定义正则但没填写。")
                return
        for name, rule in self.rules.items():
            scope = rule.get("_scope", "global")
            set_rule(self.document, name, rule, scope=scope, business_name=self.business_name)
        if not save_document(self.document):
            QMessageBox.warning(self, "保存失败", "校验规则没能保存到本机，请检查目录权限。")
            return
        self.accept()

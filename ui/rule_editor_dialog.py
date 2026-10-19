"""识别规则编辑对话框。

给"办公室里懂电脑的那个人"用的工具：当某个模板变量在规则库里没有对应的
识别规则时，在这里为它写正则，之后所有人粘贴同类数据都能自动识别。

设计要点：
  - 模板保持 {{变量名}} 不变，规则单独存 config/user_rules.json，升级不覆盖
  - 一个变量可以挂多条正则（同一个字段常有几种写法）
  - 边写边校验：语法错误、危险写法、与已有规则抢值，全部实时提示
  - 测试样本自动从"待确认区"预填，用户不用手打
  - 全文回测：直接在真实粘贴文本上跑一遍，看会命中几处

试打与真实解析走同一套代码（core.rule_store.compile_like_parser +
SmartParser），所以这里显示的命中结果就等于实际填充结果。
"""

import os
import shutil
import tempfile
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
    QVBoxLayout,
)

from core import rule_store
from core.parser import SmartParser
from core.rule_store import (
    GLOBAL_SCOPE,
    USER_SOURCE,
    add_user_rule,
    check_pattern_safety,
    find_conflicts,
    load_user_rules,
    remove_user_rule,
    rules_for_business,
    validate_pattern,
)

# 防灾难性回溯：回测文本和单个样本都设长度上限
MAX_PROBE_CHARS = 50000
MAX_SAMPLE_CHARS = 500
# 输入停顿多久后触发校验（毫秒）
DEBOUNCE_MS = 200

_GRAY = "color: #6b7280;"
_RED = "color: #dc2626; font-weight: bold;"
_GREEN = "color: #16a34a; font-weight: bold;"
_ORANGE = "color: #d97706;"


class RuleEditorDialog(QDialog):
    """为某个模板变量配置识别正则。

    :param business_name: 当前业务名，用于作用域默认值和规则筛选
    :param template_vars: 模板变量名列表，用于下拉选择
    :param target_var: 打开时默认选中的变量（通常是没匹配上规则的那个）
    :param seed_samples: 预填的测试样本，一般传"待确认区"的未识别片段
    :param probe_text: 完整粘贴文本，用于全文回测；为空则跳过回测
    """

    def __init__(self, business_name: str = "", template_vars: Optional[Sequence[str]] = None,
                 target_var: str = "", seed_samples: Optional[Sequence[str]] = None,
                 probe_text: str = "", parent=None):
        super().__init__(parent)
        self.business_name = str(business_name or "")
        self.template_vars = [str(v) for v in (template_vars or [])]
        self.probe_text = str(probe_text or "")
        self.saved = False                    # 是否成功保存过规则
        self._temp_dir: Optional[str] = None  # 回测用的临时目录，关闭时清理

        self.setWindowTitle("配置识别规则")
        self.resize(760, 720)
        self._build_ui(target_var, seed_samples or [])
        self._refresh_existing_rules()
        self._evaluate()

    # ---------- 界面 ----------

    def _build_ui(self, target_var: str, seed_samples: Sequence[str]) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel(
            "为变量写一条识别正则。同一个变量可以有多条（对应几种不同写法），"
            "命中任意一条即算识别成功。\n"
            "规则保存在本机 config/user_rules.json，软件升级不会覆盖，可复制给同事共享。")
        tip.setWordWrap(True)
        tip.setStyleSheet(_GRAY)
        layout.addWidget(tip)

        # 变量名
        var_row = QHBoxLayout()
        var_row.addWidget(QLabel("变量名："))
        self.var_combo = QComboBox()
        self.var_combo.setEditable(True)
        self.var_combo.addItems(self._var_items(target_var))
        if target_var:
            self.var_combo.setCurrentText(target_var)
        self.var_combo.currentTextChanged.connect(self._on_var_changed)
        var_row.addWidget(self.var_combo, 1)
        layout.addLayout(var_row)

        # 该变量已有的规则
        layout.addWidget(QLabel("该变量已有的规则（选中后可删除）："))
        self.existing_list = QListWidget()
        self.existing_list.setFixedHeight(72)
        self.existing_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.existing_list)

        btn_del = QPushButton("删除选中的规则")
        btn_del.clicked.connect(self._on_delete_rule)
        layout.addWidget(btn_del, alignment=Qt.AlignLeft)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        # 新正则
        layout.addWidget(QLabel("新规则的正则表达式："))
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(r"例如银行卡号：^62\d{17}$")
        self.pattern_edit.textChanged.connect(self._on_pattern_changed)
        layout.addWidget(self.pattern_edit)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet(_ORANGE)
        self.warn_label.setVisible(False)
        layout.addWidget(self.warn_label)

        # 测试样本
        layout.addWidget(QLabel(
            "测试样本（勾选 = 期望命中；已自动填入你刚才粘贴的未识别片段）："))
        self.sample_list = QListWidget()
        self.sample_list.setFixedHeight(110)
        self.sample_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.sample_list)
        for sample in seed_samples:
            self._add_sample(str(sample), expect_hit=True)

        sample_row = QHBoxLayout()
        for text, slot in [("添加样本", self._on_add_sample),
                           ("切换勾选", self._on_toggle_sample),
                           ("删除选中样本", self._on_del_sample)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            sample_row.addWidget(btn)
        sample_row.addStretch()
        layout.addLayout(sample_row)

        self.sample_result = QLabel("")
        self.sample_result.setWordWrap(True)
        layout.addWidget(self.sample_result)

        # 全文回测
        self.probe_label = QLabel("")
        self.probe_label.setWordWrap(True)
        layout.addWidget(self.probe_label)

        self.conflict_label = QLabel("")
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setStyleSheet(_RED)
        self.conflict_label.setVisible(False)
        layout.addWidget(self.conflict_label)

        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        layout.addWidget(line2)

        # 作用域
        layout.addWidget(QLabel("生效范围："))
        scope_row = QHBoxLayout()
        self.scope_business = QRadioButton(f"仅「{self.business_name or '当前业务'}」")
        self.scope_global = QRadioButton("所有业务")
        self.scope_business.setChecked(True)
        for radio in (self.scope_business, self.scope_global):
            radio.toggled.connect(lambda _checked: self._evaluate())
            scope_row.addWidget(radio)
        scope_row.addStretch()
        layout.addLayout(scope_row)

        scope_tip = QLabel("默认只对当前业务生效更安全；确认这条规则通用后再改成「所有业务」。")
        scope_tip.setStyleSheet(_GRAY)
        layout.addWidget(scope_tip)

        # 底部
        bottom = QHBoxLayout()
        bottom.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)
        self.btn_save = QPushButton("保存规则")
        self.btn_save.clicked.connect(self._on_save)
        bottom.addWidget(self.btn_save)
        layout.addLayout(bottom)

    def _var_items(self, target_var: str) -> List[str]:
        """变量下拉项：目标变量排最前，其余按模板顺序。"""
        items = [target_var] if target_var else []
        for name in self.template_vars:
            if name not in items:
                items.append(name)
        return items

    def _add_sample(self, text: str, expect_hit: bool) -> None:
        """添加一个测试样本，勾选状态表示"期望命中"。"""
        text = text.strip()[:MAX_SAMPLE_CHARS]
        if not text:
            return
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if expect_hit else Qt.Unchecked)
        item.setToolTip(text)
        self.sample_list.addItem(item)

    # ---------- 实时校验 ----------

    def _on_pattern_changed(self) -> None:
        """输入停顿后触发校验，避免每敲一个字符就跑一次正则。"""
        if not hasattr(self, "_debounce"):
            self._debounce = QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(DEBOUNCE_MS)
            self._debounce.timeout.connect(self._evaluate)
        self._debounce.start()

    def _on_var_changed(self) -> None:
        self._refresh_existing_rules()
        self._evaluate()

    def _current_field(self) -> str:
        return self.var_combo.currentText().strip()

    def _current_scope(self) -> str:
        return GLOBAL_SCOPE if self.scope_global.isChecked() else (self.business_name or GLOBAL_SCOPE)

    def _samples(self) -> List[Dict[str, object]]:
        """读取样本列表：值 + 是否期望命中。"""
        result = []
        for i in range(self.sample_list.count()):
            item = self.sample_list.item(i)
            result.append({
                "text": item.text(),
                "expect": item.checkState() == Qt.Checked,
            })
        return result

    def _refresh_existing_rules(self) -> None:
        """刷新"该变量已有的规则"列表，item 里记住全局下标以便删除。"""
        field = self._current_field()
        self.existing_list.clear()
        all_rules = load_user_rules()
        for index, rule in enumerate(all_rules):
            if rule.get("field") != field:
                continue
            scope = rule.get("scope") or GLOBAL_SCOPE
            scope_text = "所有业务" if scope == GLOBAL_SCOPE else f"仅 {scope}"
            item = QListWidgetItem(f"{rule.get('pattern')}    [{scope_text}]")
            item.setData(Qt.UserRole, index)
            item.setToolTip(rule.get("description") or rule.get("pattern"))
            self.existing_list.addItem(item)

        if self.existing_list.count() == 0:
            placeholder = QListWidgetItem("（暂无，请在下方添加第一条）")
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setForeground(Qt.gray)
            self.existing_list.addItem(placeholder)

    def _evaluate(self) -> None:
        """跑完整校验：语法 -> 危险写法 -> 样本试打 -> 全文回测 -> 冲突。"""
        pattern = self.pattern_edit.text().strip()
        self.warn_label.setVisible(False)
        self.conflict_label.setVisible(False)

        if not pattern:
            self.status_label.setText("请输入正则表达式")
            self.status_label.setStyleSheet(_GRAY)
            self.sample_result.setText("")
            self.probe_label.setText("")
            self.btn_save.setEnabled(False)
            return

        # 1. 语法校验（解析器以前是静默跳过非法正则，这里必须报出来）
        ok, error = validate_pattern(pattern)
        if not ok:
            self.status_label.setText(f"✗ 正则语法有误：{error}")
            self.status_label.setStyleSheet(_RED)
            self.sample_result.setText("")
            self.probe_label.setText("")
            self.btn_save.setEnabled(False)
            return

        self.status_label.setText("✓ 语法正确")
        self.status_label.setStyleSheet(_GREEN)
        self.btn_save.setEnabled(True)

        # 2. 危险写法警告（不阻止保存，决定权在用户）
        warnings = check_pattern_safety(pattern)
        if warnings:
            self.warn_label.setText("⚠ " + "\n⚠ ".join(warnings))
            self.warn_label.setVisible(True)

        self._evaluate_samples(pattern)
        self._evaluate_probe(pattern)
        self._evaluate_conflicts(pattern)

    def _evaluate_samples(self, pattern: str) -> None:
        """用样本试打，并把结果写回每个样本的显示状态。"""
        samples = self._samples()
        if not samples:
            self.sample_result.setText("（没有测试样本，可点「添加样本」手动输入一个真实值）")
            self.sample_result.setStyleSheet(_GRAY)
            return

        try:
            compiled = rule_store.compile_like_parser(pattern)
        except Exception as exc:  # 理论上不会到这，validate 已拦下
            self.sample_result.setText(f"试打失败：{exc}")
            self.sample_result.setStyleSheet(_RED)
            return

        passed = failed = 0
        lines = []
        for sample in samples:
            text = str(sample["text"])
            hit = bool(compiled.match(text))
            expect = bool(sample["expect"])
            if hit == expect:
                passed += 1
                mark = "✓ 命中" if hit else "✓ 未命中"
            else:
                failed += 1
                mark = "✗ 意外命中" if hit else "✗ 未命中（期望命中）"
            lines.append(f"  {mark}  {text}")

        summary = f"样本试打：{passed} 个符合预期"
        if failed:
            summary += f"，{failed} 个不符合"
        self.sample_result.setText(summary + "\n" + "\n".join(lines))
        self.sample_result.setStyleSheet(_RED if failed else _GREEN)

    def _evaluate_probe(self, pattern: str) -> None:
        """在完整粘贴文本上跑真实解析，看这条规则实际会命中哪些值。"""
        if not self.probe_text.strip():
            self.probe_label.setText("")
            return

        field = self._current_field()
        if not field:
            self.probe_label.setText("")
            return

        hits = self._run_probe(pattern, field)
        if hits is None:
            self.probe_label.setText("全文回测：暂不可用")
            self.probe_label.setStyleSheet(_GRAY)
            return

        if not hits:
            self.probe_label.setText(
                "全文回测：在你粘贴的内容里 0 处命中。"
                "如果预期应该命中，说明正则写窄了，或该值已被其他规则先抢走。")
            self.probe_label.setStyleSheet(_ORANGE)
            return

        shown = "、".join(hits[:6]) + ("…" if len(hits) > 6 else "")
        self.probe_label.setText(f"全文回测：命中 {len(hits)} 处 → {shown}")
        self.probe_label.setStyleSheet(_GREEN if len(hits) <= 3 else _ORANGE)

    def _run_probe(self, pattern: str, field: str) -> Optional[List[str]]:
        """构造临时规则文件跑一次真实解析，返回新规则命中的值列表。

        临时文件里放"当前业务已有的用户规则 + 正在编辑的这条"，
        内置规则由 SmartParser 自己从 rules.json 加载，
        这样回测结果才和真实填充完全一致（包括被内置规则抢值的情况）。
        """
        try:
            if self._temp_dir is None:
                self._temp_dir = tempfile.mkdtemp(prefix="docfill_rule_preview_")
            temp_rules = os.path.join(self._temp_dir, "preview_rules.json")

            existing = rules_for_business(load_user_rules(), self.business_name)
            existing = [r for r in existing
                        if not (r.get("field") == field and r.get("pattern") == pattern)]
            existing.append({
                "field": field, "pattern": pattern, "priority": rule_store.next_priority(existing),
                "label": field, "description": "", "scope": self._current_scope(),
                "source": USER_SOURCE, "samples": [], "created_at": "",
            })
            rule_store.save_user_rules(existing, temp_rules)

            parser = SmartParser(business_name=self.business_name, user_rules_path=temp_rules)
            result = parser.parse(self.probe_text[:MAX_PROBE_CHARS])
            return [f.value for f in result.fields if f.field == field]
        except Exception:
            return None

    def _evaluate_conflicts(self, pattern: str) -> None:
        """检查新正则会不会和已有规则抢同一个值。"""
        field = self._current_field()
        samples = [str(s["text"]) for s in self._samples()]

        # 对手规则 = 内置规则 + 其他用户规则（排除本变量自己的规则）
        probe_parser = SmartParser(business_name=self.business_name)
        others = [r for r in probe_parser.rules if r.get("field") != field]

        messages = find_conflicts(pattern, others, samples)
        if messages:
            self.conflict_label.setText("⚠ 规则冲突：\n" + "\n".join(messages[:6]))
            self.conflict_label.setVisible(True)

    # ---------- 操作 ----------

    def _on_add_sample(self) -> None:
        text, ok = QInputDialog.getText(self, "添加测试样本", "粘贴一个该变量的真实值：")
        if not ok:
            return
        text = text.strip()
        if not text:
            return
        self._add_sample(text, expect_hit=True)
        self._evaluate()

    def _on_toggle_sample(self) -> None:
        item = self.sample_list.currentItem()
        if not item:
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self._evaluate()

    def _on_del_sample(self) -> None:
        row = self.sample_list.currentRow()
        if row < 0:
            return
        self.sample_list.takeItem(row)
        self._evaluate()

    def _on_delete_rule(self) -> None:
        item = self.existing_list.currentItem()
        if not item:
            return
        index = item.data(Qt.UserRole)
        if index is None:
            return  # 选中的是占位行
        ok, error = remove_user_rule(int(index))
        if not ok:
            self.status_label.setText(f"删除失败：{error}")
            self.status_label.setStyleSheet(_RED)
            return
        self.saved = True
        self._refresh_existing_rules()
        self._evaluate()

    def _on_save(self) -> None:
        pattern = self.pattern_edit.text().strip()
        field = self._current_field()
        if not field:
            self.status_label.setText("✗ 请先选择或输入变量名")
            self.status_label.setStyleSheet(_RED)
            return

        ok, error = validate_pattern(pattern)
        if not ok:
            self.status_label.setText(f"✗ 正则语法有误：{error}")
            self.status_label.setStyleSheet(_RED)
            return

        samples = [str(s["text"]) for s in self._samples() if s["expect"]]
        ok, error = add_user_rule(
            field=field,
            pattern=pattern,
            scope=self._current_scope(),
            samples=samples,
            description="由「配置识别规则」界面添加",
        )
        if not ok:
            self.status_label.setText(f"✗ 保存失败：{error}")
            self.status_label.setStyleSheet(_RED)
            return

        self.saved = True
        self.pattern_edit.clear()
        self._refresh_existing_rules()
        self.status_label.setText(f"✓ 已保存：{field} ← {pattern}")
        self.status_label.setStyleSheet(_GREEN)
        self._evaluate()

    # ---------- 生命周期 ----------

    def done(self, result: int) -> None:
        """关闭时清理回测用的临时目录。"""
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
        super().done(result)

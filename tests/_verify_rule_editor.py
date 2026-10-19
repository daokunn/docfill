"""验证规则编辑器端到端：写规则 -> 落盘 -> 真实解析命中新变量。

跑完会恢复真实的 config/user_rules.json，不污染用户配置。
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from core import rule_store
from core.parser import SmartParser
from ui.rule_editor_dialog import RuleEditorDialog

app = QApplication.instance() or QApplication(sys.argv)

# 默认参数在函数定义时就绑定了真实路径，monkeypatch 无效，
# 所以这里备份真实规则文件，跑完恢复。
REAL_RULES = rule_store.USER_RULES_FILE
_backup = None
if os.path.exists(REAL_RULES):
    with open(REAL_RULES, encoding="utf-8") as handle:
        _backup = handle.read()


def restore():
    content = _backup if _backup is not None else '{"_说明": "", "rules": []}\n'
    with open(REAL_RULES, "w", encoding="utf-8") as handle:
        handle.write(content)


PATTERN = r"^62\d{17}$"
PROBE = "张三 6217001234567890123 建行赣州分行营业部 6228489876543210987"
EMPTY_RULES = os.path.join(os.path.dirname(REAL_RULES), "_empty_probe.json")


def main():
    with open(EMPTY_RULES, "w", encoding="utf-8") as handle:
        handle.write('{"rules": []}')

    try:
        dialog = RuleEditorDialog(
            business_name="公务卡申请",
            template_vars=["姓名", "卡号", "开户行"],
            target_var="卡号",
            seed_samples=["6217001234567890123", "建行赣州分行营业部"],
            probe_text=PROBE,
        )
        dialog.pattern_edit.setText(PATTERN)
        dialog._evaluate()

        print("=== 编辑中实时反馈 ===")
        print("状态:", dialog.status_label.text())
        print("试打:", dialog.sample_result.text().replace("\n", " | "))
        print("回测:", dialog.probe_label.text())
        print("警告可见:", dialog.warn_label.isVisible())
        print("冲突可见:", dialog.conflict_label.isVisible())

        dialog._on_save()
        print("\n=== 保存结果 ===")
        print("saved:", dialog.saved)
        for rule in rule_store.load_user_rules():
            print("规则:", rule["field"], "|", rule["pattern"], "| scope:", rule["scope"])
        dialog.done(0)

        print("\n=== 规则生效验证 ===")
        before = SmartParser(business_name="公务卡申请", user_rules_path=EMPTY_RULES)
        print("配规则前:", before.to_variable_dict(before.parse(PROBE)))

        after = SmartParser(business_name="公务卡申请", user_rules_path=REAL_RULES)
        print("配规则后:", after.to_variable_dict(after.parse(PROBE)))

        other = SmartParser(business_name="信用卡激活", user_rules_path=REAL_RULES)
        print("其他业务:", other.to_variable_dict(other.parse(PROBE)))

        print("\n=== 冲突检测验证 ===")
        dialog2 = RuleEditorDialog(
            business_name="公务卡申请",
            template_vars=["姓名", "卡号"],
            target_var="卡号",
            seed_samples=["张三"],
            probe_text=PROBE,
        )
        dialog2.pattern_edit.setText(r"^[一-龥]{2,4}$")
        dialog2._evaluate()
        print("冲突提示:", dialog2.conflict_label.text().replace("\n", " "))
        print("冲突可见:", dialog2.conflict_label.isVisible())
        dialog2.done(0)

        print("\n=== 危险正则警告 ===")
        dialog3 = RuleEditorDialog(business_name="x", template_vars=["卡号"], target_var="卡号")
        dialog3.pattern_edit.setText(".*")
        dialog3._evaluate()
        print("警告:", dialog3.warn_label.text())
        dialog3.done(0)

        print("\nDONE")
    finally:
        if os.path.exists(EMPTY_RULES):
            os.remove(EMPTY_RULES)


try:
    main()
finally:
    restore()
    print("已恢复真实规则文件")

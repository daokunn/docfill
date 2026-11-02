"""变量规则（默认值/公式/辅助变量）与切片表达式回归测试。"""

import json

import core.variable_rules as variable_rules
from core.expression import evaluate
from core.variable_manager import VariableManager


def test_slice_and_numeric_add():
    assert evaluate("身份证号[6:14]", {"身份证号": "360700199001011234"}) == "19900101"
    assert evaluate("手机号[-4:]", {"手机号": "13812345678"}) == "5678"
    assert evaluate("本金 + 利息", {"本金": "100", "利息": "200"}) == 300


def test_blank_optional_operands_are_ignored():
    assert evaluate("B+C+D+E", {"B": "1", "C": "2", "D": "3", "E": ""}) == 6
    assert evaluate("B+C+D+E", {"B": "", "C": "2", "D": "3", "E": "4"}) == 9
    assert evaluate("B+C", {"B": "张三", "C": ""}) == "张三"
    assert evaluate("B/E", {"B": "100", "E": ""}) == ""


def test_user_rules_default_formula_aux(tmp_path, monkeypatch):
    rules_file = tmp_path / "user_variable_rules.json"
    rules_file.write_text(json.dumps({
        "businesses": {
            "测试": {
                "单位": {"mode": "default", "expr": "测试单位", "apply_on_empty": False},
                "出生日期": {"mode": "formula", "expr": "身份证号[6:14]"},
                "总额": {"mode": "formula", "expr": "本金 + 利息", "decimals": 2},
                "期限月数": {
                    "mode": "formula", "expr": "本金 / 100",
                    "decimals": 0, "kind": "aux", "export_summary": True,
                },
            }
        }
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(variable_rules, "RULES_FILE", str(rules_file))

    vm = VariableManager("测试")
    vm.init_from_template_vars(
        ["姓名", "身份证号", "单位", "出生日期", "本金", "利息", "总额"])
    vm.set_value("姓名", "张三")
    vm.set_value("身份证号", "360700199001011234")
    vm.set_value("本金", "0.5")
    vm.set_value("利息", "0.505")

    values = vm.get_output_values()
    assert values["单位"] == "测试单位"
    assert values["出生日期"] == "1990年1月1日"
    assert values["总额"] == "1.01"
    assert values["期限月数"] == 0

    # 名单批量模式：未勾选“空白时套用”的默认值不应自动出现
    batch = VariableManager("测试", apply_defaults_on_empty=False)
    batch.init_from_template_vars(["单位"])
    assert batch.get_all_resolved()["单位"] == ""

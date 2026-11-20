"""智能粘贴解析回归测试：假冲突 / 值乱跳 / 别名映射。

对应用户反馈：
- 同一人的证件写成"身份证号"和"证件号"两种叫法，值相同却被判冲突；
- 宽泛的自定义正则抢占了身份证等值，导致值"跳到别的变量"；
- 模板同时存在标准名和别名时，识别值应写入标准名变量，不能写进别名变量。
"""

from core.field_mapper import match_template_variable
from core.parser import SmartParser


def test_same_value_under_two_aliases_is_not_a_conflict():
    """身份证号 + 证件号 两种写法、同一个值，不应判为冲突。"""
    parser = SmartParser()
    result = parser.parse("姓名：张三\n身份证号：360700199001011234\n证件号：360700199001011234")
    id_fields = [f for f in result.fields if f.field == "身份证号"]
    assert len(id_fields) == 1
    assert id_fields[0].conflict is False
    assert "身份证号" not in result.conflicts
    assert id_fields[0].value == "360700199001011234"


def test_different_values_under_two_aliases_still_conflict():
    """两个别名对应不同的值，仍应判冲突（保留原有能力）。"""
    parser = SmartParser()
    result = parser.parse("身份证号：360700199001011234\n证件号：110101199003078888")
    assert "身份证号" in result.conflicts


def test_broad_user_rule_does_not_steal_id_card():
    """用户写了 .* 这种宽泛正则时，不应抢走身份证号等强格式字段的值。"""
    parser = SmartParser()
    parser.rules = [
        {"field": "备注", "pattern": r".*", "priority": 1, "label": "备注", "source": "user"},
        {"field": "身份证号", "pattern": r"^\d{17}[\dXx]$", "priority": 1, "label": "身份证号"},
    ]
    parser._compile_rules()
    result = parser.parse("360700199001011234")
    values = {f.field: f.value for f in result.fields}
    assert values.get("身份证号") == "360700199001011234", values
    assert "备注" not in values or values["备注"] != "360700199001011234"


def test_exact_standard_name_wins_over_alias_in_template():
    """模板同时有'证件号'和'身份证号'时，识别字段'身份证号'必须写标准名。"""
    template = ["姓名", "证件号", "身份证号", "手机号"]
    assert match_template_variable("身份证号", template) == "身份证号"


def test_alias_fallback_only_when_standard_absent():
    """模板没有标准名、只有别名时，才回退到别名变量。"""
    template = ["姓名", "证件号", "手机号"]
    assert match_template_variable("身份证号", template) == "证件号"

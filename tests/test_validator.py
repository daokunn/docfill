"""变量校验引擎测试。

覆盖：身份证校验位、手机号、内置预设、自定义正则、
全局/业务作用域、空值跳过、开关关闭。
"""

from core.validator import (
    validate_value,
    collect_issues,
    empty_document,
    set_rule,
    PRESET_ID_CARD,
    PRESET_PHONE,
)


VALID_ID = "36070019900101123X"   # 校验位经验证正确
BAD_ID = "360700199001011234"     # 校验位错误


def test_id_card_preset_accepts_valid_checksum():
    assert validate_value(VALID_ID, {"preset": PRESET_ID_CARD}) == ""


def test_id_card_preset_rejects_bad_checksum():
    msg = validate_value(BAD_ID, {"preset": PRESET_ID_CARD})
    assert msg  # 有错误提示


def test_id_card_preset_rejects_wrong_length():
    assert validate_value("12345", {"preset": PRESET_ID_CARD})


def test_phone_preset():
    assert validate_value("13812345678", {"preset": PRESET_PHONE}) == ""
    assert validate_value("12345", {"preset": PRESET_PHONE})


def test_empty_value_is_skipped():
    """空值交由原有的空变量检查处理，校验器不重复报错。"""
    assert validate_value("", {"preset": PRESET_PHONE, "regex": "^\\d+$"}) == ""
    assert validate_value("   ", {"preset": PRESET_ID_CARD}) == ""


def test_custom_regex_rule():
    rule = {"preset": "", "regex": "^[\\u4e00-\\u9fa5]{2,4}$", "message": "请填2-4个汉字"}
    assert validate_value("张三", rule) == ""
    assert validate_value("John", rule) == "请填2-4个汉字"


def test_invalid_custom_regex_is_ignored():
    rule = {"preset": "", "regex": "([unclosed", "message": "x"}
    assert validate_value("anything", rule) == ""


def test_collect_issues_uses_business_scope():
    doc = empty_document()
    set_rule(doc, "经办人", {"preset": "", "regex": "^李", "message": "必须姓李"},
             scope="global")
    set_rule(doc, "金额", {"preset": "number", "message": "金额须为数字"},
             scope="business", business_name="公务卡申请")

    # 全局规则对其他业务生效：张三不匹配 → 报错
    issues = collect_issues({"经办人": "张三"}, doc, business_name="其他业务", enabled=True)
    assert any("必须姓李" in i.message for i in issues)

    # 业务专属规则只对公务卡申请生效
    issues = collect_issues({"金额": "abc"}, doc, business_name="公务卡申请", enabled=True)
    assert any("金额须为数字" in i.message for i in issues)
    issues = collect_issues({"金额": "abc"}, doc, business_name="其他业务", enabled=True)
    assert issues == []


def test_collect_issues_disabled_returns_empty():
    doc = empty_document()
    set_rule(doc, "身份证号", {"preset": PRESET_ID_CARD}, scope="global")
    issues = collect_issues({"身份证号": BAD_ID}, doc, business_name="x", enabled=False)
    assert issues == []

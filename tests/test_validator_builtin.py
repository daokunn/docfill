"""内置校验开箱即用测试（TDD）。

背景：文档承诺"身份证/手机号开箱即用"，但用户没配置规则时
load_document() 返回空文档，导致填错的身份证根本不被拦截。
本测试锁定期望：按变量名自动套用内置预设，且用户显式规则优先。
"""

from core.validator import (
    collect_issues,
    empty_document,
    set_rule,
    default_rule_for_variable,
    PRESET_ID_CARD,
    PRESET_PHONE,
    PRESET_EMAIL,
    PRESET_CUSTOM,
)


BAD_ID = "360700199001011234"   # 校验位错误
GOOD_ID = "36070019900101123X"


def test_builtin_id_card_rule_by_variable_name():
    """身份证号/证件号/身份证 等变量名自动套内置校验，无需用户配置。"""
    for name in ("身份证号", "身份证", "证件号", "身份证号码"):
        rule = default_rule_for_variable(name)
        assert rule is not None, name
        assert rule["preset"] == PRESET_ID_CARD, name


def test_builtin_phone_and_email_by_variable_name():
    assert default_rule_for_variable("手机号")["preset"] == PRESET_PHONE
    assert default_rule_for_variable("联系电话")["preset"] == PRESET_PHONE
    assert default_rule_for_variable("邮箱")["preset"] == PRESET_EMAIL


def test_unknown_variable_has_no_builtin_rule():
    assert default_rule_for_variable("备注") is None


def test_collect_issues_applies_builtin_when_no_user_rule():
    """没有用户规则时，错身份证必须被拦下（回归 P1 核心缺陷）。"""
    doc = empty_document()
    issues = collect_issues({"身份证号": BAD_ID}, doc, business_name="贷款")
    assert issues, "错身份证应被内置规则拦下"
    assert issues[0].variable == "身份证号"
    assert "校验位" in issues[0].message or "不合法" in issues[0].message


def test_collect_issues_builtin_accepts_valid_value():
    doc = empty_document()
    assert collect_issues({"身份证号": GOOD_ID}, doc, business_name="贷款") == []


def test_explicit_user_rule_overrides_builtin():
    """用户显式关掉/改写规则时，以用户规则为准。"""
    doc = empty_document()
    set_rule(doc, "身份证号", {"preset": PRESET_CUSTOM, "regex": ".*", "enabled": True},
             scope="global")
    # 用户的宽松规则放行 → 不再报内置身份证错误
    assert collect_issues({"身份证号": BAD_ID}, doc, business_name="贷款") == []


def test_disabled_user_rule_disables_builtin():
    """用户显式禁用该变量校验 → 内置也不再生效。"""
    doc = empty_document()
    set_rule(doc, "身份证号", {"preset": PRESET_ID_CARD, "enabled": False},
             scope="global")
    assert collect_issues({"身份证号": BAD_ID}, doc, business_name="贷款") == []


def test_builtin_can_be_globally_disabled():
    """设置里关闭内置预设（但保留用户自定义规则）时应只跑自定义。"""
    doc = empty_document()
    issues = collect_issues({"身份证号": BAD_ID}, doc, business_name="贷款",
                            use_builtin=False)
    assert issues == []

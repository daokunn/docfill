"""变量智能分组排序的最小回归测试。"""

from core.variable_groups import group_of, smart_order


def test_basic_info_grouped_before_time_and_amount():
    names = ["申请日期", "姓名", "贷款金额", "身份证号", "分期起止年月", "手机号"]
    assert smart_order(names) == [
        "姓名", "身份证号", "手机号",
        "申请日期", "分期起止年月",
        "贷款金额",
    ]


def test_group_of_common_fields():
    assert group_of("姓名") == "基本信息"
    assert group_of("身份证号码") == "基本信息"
    assert group_of("出生日期") == "基本信息"
    assert group_of("申请日期") == "时间信息"
    assert group_of("分期起止年月") == "时间信息"
    assert group_of("贷款金额") == "金额信息"

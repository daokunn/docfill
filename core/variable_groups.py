"""变量语义分组与智能排序。

目的：让变量表按"人怎么填"排列，而不是完全按模板出现顺序：
  基本信息（姓名/证件/电话等）→ 时间信息 → 金额信息 → 其他

识别依据是变量名关键词，不做语义模型；识别不了就留在“其他”，
用户仍可手动拖拽调整，并保存为自定义顺序。
"""

from typing import Dict, List, Sequence, Tuple

GROUP_BASIC = "基本信息"
GROUP_TIME = "时间信息"
GROUP_AMOUNT = "金额信息"
GROUP_OTHER = "其他信息"

GROUP_ORDER = (GROUP_BASIC, GROUP_TIME, GROUP_AMOUNT, GROUP_OTHER)

# 关键词顺序很重要：同时命中时先看“基本信息”，例如“出生日期”归到基本信息
_BASIC_KEYWORDS = (
    "姓名", "名字", "客户名", "客户", "身份证", "证件", "性别", "出生",
    "生日", "年龄", "民族", "籍贯", "户籍", "婚姻", "学历",
    "手机", "电话", "联系方式", "邮箱", "微信", "地址", "住址", "邮编",
    "单位", "公司", "部门", "职务", "职业",
)
_TIME_KEYWORDS = (
    "日期", "时间", "年月", "年份", "月份", "年度", "起止", "期间",
    "期限", "有效期", "到期", "起始", "截止",
)
_AMOUNT_KEYWORDS = (
    "金额", "费用", "余额", "利率", "价格", "收入", "贷款", "额度",
    "税额", "本金", "利息", "总额", "合计", "小计", "总计",
)


def group_of(name: str) -> str:
    """按变量名判断分组；判断不了归“其他信息”。"""
    text = str(name or "")
    if any(keyword in text for keyword in _BASIC_KEYWORDS):
        return GROUP_BASIC
    if any(keyword in text for keyword in _TIME_KEYWORDS):
        return GROUP_TIME
    if any(keyword in text for keyword in _AMOUNT_KEYWORDS):
        return GROUP_AMOUNT
    return GROUP_OTHER


def smart_order(names: Sequence[str]) -> List[str]:
    """按分组重排，组内保持原有顺序（稳定排序）。"""
    ordered = [str(name) for name in names]
    position = {name: index for index, name in enumerate(ordered)}
    group_rank = {name: index for index, name in enumerate(GROUP_ORDER)}
    return sorted(
        ordered,
        key=lambda name: (group_rank.get(group_of(name), len(GROUP_ORDER)),
                          position.get(name, 0)),
    )


def grouped_names(names: Sequence[str]) -> List[Tuple[str, str]]:
    """返回 [(变量名, 分组)]，顺序为智能分组顺序。"""
    return [(name, group_of(name)) for name in smart_order(names)]


def group_counts(names: Sequence[str]) -> Dict[str, int]:
    """统计每个分组有多少变量，供界面/日志使用。"""
    counts = {group: 0 for group in GROUP_ORDER}
    for name in names:
        group = group_of(name)
        counts[group] = counts.get(group, 0) + 1
    return counts

"""变量名语义映射。

智能粘贴识别出来的字段名（如“开始日期”）和模板里的变量名（如“开始时间”）
经常不一致。本模块用别名表把两者归一到同一个语义，再映射到模板变量。
"""

from typing import List, Sequence

from core.alias_mapper import get_alias_mapper

# 时间段拆出来的三个标准字段
CANONICAL_DATE_FIELDS = ("开始日期", "结束日期", "起止日期")

# 地址拆分产生的派生字段：模板没有对应变量时不应写进结果
ADDRESS_DERIVED_FIELDS = ("省", "市", "区", "详细地址")


def canonical_field(name: str) -> str:
    """把变量名归一化为语义标准名；别名表里没有的保持原名。"""
    name = str(name or "").strip()
    if not name:
        return ""
    return get_alias_mapper().normalize(name)


def match_template_variable(field: str, template_vars: Sequence[str]) -> str:
    """为一个识别字段找到最合适的模板变量名。

    优先级：
    1. 完全同名
    2. 标准名与模板变量完全相同
    3. 标准名与模板变量经别名表归一后相同
    4. 姓名 / 客户名 互相兜底
    """
    field = str(field or "").strip()
    if not field:
        return ""

    names = [str(v) for v in template_vars]
    if field in names:
        return field

    canon = canonical_field(field)
    if not canon:
        return ""

    if canon in names:
        return canon

    for name in names:
        if canonical_field(name) == canon:
            return name

    # 模板只有“姓名”或只有“客户名”时，允许互相兜底
    if canon in ("姓名", "客户名"):
        fallback = "客户名" if canon == "姓名" else "姓名"
        if fallback in names:
            return fallback

    return ""


def map_fields_to_template(fields: List, template_vars: Sequence[str]) -> List:
    """就地给字段补上模板目标名，返回处理后的字段列表。

    - 匹配到的字段：field 改成模板变量名，mapped_from 记录原字段名
    - 未匹配字段：in_template=False，由弹窗展示为“模板中无”
    - 地址派生字段 / 多余的“起止日期”在模板不需要时直接丢弃
    """
    template_vars = [str(v) for v in template_vars]
    targets = {}
    for field in fields:
        targets[id(field)] = match_template_variable(field.field, template_vars)

    start_end_matched = any(
        field.field in ("开始日期", "结束日期") and targets.get(id(field))
        for field in fields
    )

    mapped = []
    for field in fields:
        original = field.field
        target = targets.get(id(field), "")

        if target:
            field.field = target
            field.label = target
            field.mapped_from = original if original != target else ""
            field.in_template = True
            mapped.append(field)
            continue

        # 模板只要起止时间时，不再塞一个多余的“起止日期”
        if original == "起止日期" and start_end_matched:
            continue

        # 模板没有省/市/区变量时，地址拆分结果只作为参考，不进入结果表
        if original in ADDRESS_DERIVED_FIELDS:
            continue

        field.in_template = False
        mapped.append(field)

    # 按模板变量顺序展示，避免“开始时间”总排在姓名前面
    order = {str(name): index for index, name in enumerate(template_vars)}
    mapped.sort(key=lambda item: order.get(item.field, len(order)))
    return mapped

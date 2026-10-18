"""生成前检查：找出模板里仍然为空的变量。"""

from typing import Dict, List

from core.scanner import BusinessInfo


def collect_empty_variables(business: BusinessInfo, values: Dict[str, object]) -> List[str]:
    """返回模板中存在、但输出值仍为空的变量名（去重、稳定排序）。

    只检查模板实际声明的变量，不会把自定义变量误报进来。
    """
    empty = set()
    optional = getattr(business, "optional_variables", set())
    for template in business.templates:
        if template.error:
            continue
        for name in template.variables:
            if name in optional:
                continue
            if not str(values.get(name, "")).strip():
                empty.add(name)
    return sorted(empty)


def format_empty_summary(business_name: str, empty_variables: List[str], limit: int = 12) -> str:
    """生成适合弹窗/日志展示的缺失变量摘要。"""
    if not empty_variables:
        return f"业务「{business_name}」的模板变量已全部填写。"
    shown = "、".join(empty_variables[:limit])
    if len(empty_variables) > limit:
        shown += f" 等 {len(empty_variables)} 个"
    return f"业务「{business_name}」有 {len(empty_variables)} 个变量为空：{shown}"

"""生成前检查：找出模板里仍然为空的变量。

界面展示约定：变量不多时在确认框里全部就地列出；变量多时只露前几个，
其余收进同一个界面的"详细查看"里就地展开——不额外开窗口。
"""

from typing import Any, Dict, List

from core.scanner import BusinessInfo

# 超过这个数量就把明细收进"详细查看"（就地展开，不新开窗口）
INLINE_DETAIL_THRESHOLD = 8


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


def should_collapse_details(count: int, threshold: int = INLINE_DETAIL_THRESHOLD) -> bool:
    """变量条数是否超过就地直出的阈值，需要"详细查看"按钮。

    只做数量判断，保持纯函数便于测试；阈值可被设置覆盖。
    """
    return max(0, int(count or 0)) > max(1, int(threshold or INLINE_DETAIL_THRESHOLD))


def format_missing_section(
    names: List[str], threshold: int = INLINE_DETAIL_THRESHOLD
) -> Dict[str, Any]:
    """把缺失变量整理成"就地展示 + 可展开明细"的展示数据。

    返回 dict：
      - visible / hidden：直接显示 / 收进详细查看的变量名
      - total：总数
      - needs_detail_button：是否需要"详细查看"按钮
    这样界面层无需自己判断阈值，也不必弹第二个窗口。
    """
    cleaned = [str(n).strip() for n in (names or []) if str(n).strip()]
    collapse = should_collapse_details(len(cleaned), threshold)
    limit = max(1, int(threshold or INLINE_DETAIL_THRESHOLD))
    if collapse:
        return {
            "visible": cleaned[:limit],
            "hidden": cleaned[limit:],
            "total": len(cleaned),
            "needs_detail_button": True,
        }
    return {
        "visible": list(cleaned),
        "hidden": [],
        "total": len(cleaned),
        "needs_detail_button": False,
    }


def should_warn_incomplete_paste(filled: int, total: int) -> bool:
    """智能粘贴确认时，是否要拦截"大片待填写"。

    只差一两个变量（如可选备注）时不打扰用户——生成前的"生成前检查"
    才是最后防线，会尊重可选变量并给出完整清单。这里只在明显大片空白
    （缺失 >= 3 个，或填入不到一半）时才提前提醒，避免同一批空变量弹两次。
    """
    filled = max(0, int(filled or 0))
    total = max(0, int(total or 0))
    if total == 0 or filled >= total:
        return False
    missing = total - filled
    return missing >= 3 or filled * 2 < total

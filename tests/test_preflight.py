"""生成前检查：缺失变量就地展示的数据整理逻辑（不多开窗口）。"""

from core.preflight import (
    INLINE_DETAIL_THRESHOLD,
    format_missing_section,
    should_collapse_details,
)


def test_few_variables_show_inline_without_button():
    """变量不多：全部就地输出，不需要'详细查看'按钮。"""
    section = format_missing_section(["姓名", "手机号"])
    assert section["total"] == 2
    assert section["visible"] == ["姓名", "手机号"]
    assert section["hidden"] == []
    assert section["needs_detail_button"] is False
    assert not should_collapse_details(2)


def test_many_variables_collapse_behind_button():
    """变量多：只显示前几个，其余收进'详细查看'，仍在同一界面。"""
    names = [f"字段{i}" for i in range(INLINE_DETAIL_THRESHOLD + 5)]
    section = format_missing_section(names)
    assert section["total"] == len(names)
    assert section["visible"] == names[:INLINE_DETAIL_THRESHOLD]
    assert section["hidden"] == names[INLINE_DETAIL_THRESHOLD:]
    assert section["needs_detail_button"] is True
    assert should_collapse_details(len(names))


def test_threshold_boundary():
    names = [f"字段{i}" for i in range(INLINE_DETAIL_THRESHOLD)]
    assert not should_collapse_details(len(names))
    assert should_collapse_details(len(names) + 1)


def test_empty_missing():
    section = format_missing_section([])
    assert section["total"] == 0
    assert section["visible"] == []
    assert section["needs_detail_button"] is False

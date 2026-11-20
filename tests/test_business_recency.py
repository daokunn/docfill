# -*- coding: utf-8 -*-
"""业务列表"最近使用置顶"逻辑测试。"""
from core.scanner import BusinessInfo, sort_businesses_by_recency, touch_recent_business


def _biz(name):
    return BusinessInfo(name=name, path="")


def test_touch_moves_name_to_front_and_dedups():
    recent = ["A", "B", "C"]
    out = touch_recent_business(recent, "C")
    assert out[0] == "C"
    assert out.count("C") == 1
    assert out == ["C", "A", "B"]


def test_touch_new_name_inserts_front_and_caps_limit():
    recent = ["A", "B"]
    out = touch_recent_business(recent, "D", limit=3)
    assert out == ["D", "A", "B"]


def test_sort_recent_first_then_alphabetical():
    biz = [_biz(n) for n in ["降额", "公务卡申请", "信用卡激活"]]
    recent = ["信用卡激活", "降额"]
    out = sort_businesses_by_recency(biz, recent)
    assert [b.name for b in out] == ["信用卡激活", "降额", "公务卡申请"]


def test_sort_with_empty_recent_keeps_original_order():
    biz = [_biz(n) for n in ["降额", "公务卡申请"]]
    out = sort_businesses_by_recency(biz, [])
    assert [b.name for b in out] == ["降额", "公务卡申请"]

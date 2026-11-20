# -*- coding: utf-8 -*-
"""地址拆分不能让模板只有 {{地址}} 时丢失省市信息。

真实痛点：模板只有"地址"变量，解析把"江西省赣州市章贡区红旗大道123号"
拆成省/市/区+详细地址，然后把地址覆盖成"红旗大道123号"，省市区又因
模板没有对应变量被丢弃 → 文档里地址只剩半截。
"""
from core.parser import SmartParser
from core.field_mapper import map_fields_to_template


def test_full_address_kept_when_template_has_no_subfields():
    parser = SmartParser()
    result = parser.parse("姓名：张三\n地址：江西省赣州市章贡区红旗大道123号")
    fields = map_fields_to_template(result.fields, ["姓名", "地址"])
    addr = next(f for f in fields if f.field == "地址")
    assert "江西" in addr.value and "赣州" in addr.value, addr.value
    assert "红旗大道" in addr.value, addr.value


def test_address_split_when_template_has_subfields():
    """模板有省/市/区变量时，仍按拆分结果填入各自变量。"""
    parser = SmartParser()
    result = parser.parse("地址：江西省赣州市章贡区红旗大道123号")
    fields = map_fields_to_template(result.fields, ["地址", "省", "市", "区"])
    names = {f.field: f.value for f in fields}
    assert names.get("省") == "江西省"
    assert names.get("市") == "赣州市"
    assert "红旗大道" in names.get("地址", "")


def test_incomplete_warn_only_on_large_gaps():
    """粘贴确认的拦截只在'大片空白'时触发，差一两个变量不打扰。"""
    from core.preflight import should_warn_incomplete_paste
    # 20 个变量填 3 个 → 拦
    assert should_warn_incomplete_paste(filled=3, total=20) is True
    # 8 个填 7 个（只差备注）→ 不拦
    assert should_warn_incomplete_paste(filled=7, total=8) is False
    # 全填 → 不拦
    assert should_warn_incomplete_paste(filled=8, total=8) is False

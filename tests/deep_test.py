"""
第二轮深度测试 - 挖掘更隐蔽的边界 Bug
重点测试：KV分隔符歧义、地址拆分、日期归一化、表达式边界、渲染边界
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.parser import SmartParser
from core.expression import evaluate, try_evaluate, is_expression, ExpressionError
from core.variable_manager import VariableManager
from core.scanner import extract_variables_from_text, rename_variables_in_text

passed = 0
failed = 0
bugs = []


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")


def record_bug(module, desc, detail=""):
    bugs.append((module, desc, detail))
    print(f"  [BUG] [{module}] {desc}")
    if detail:
        print(f"        详情: {detail}")


def test_kv_edge_cases():
    print("\n--- KV 分隔符边界 ---")
    p = SmartParser()

    # "不是" 可能被误拆
    r = p.parse("姓名不是张三")
    d = p.to_variable_dict(r)
    # 期望：key="姓名不", value="张三" 或者不识别
    # 检查是否产生奇怪的字段
    print(f"    '姓名不是张三' -> {d}")
    test("'不是'不产生错误字段", "姓名不" not in d or d.get("姓名") is not None,
         f"实际: {d}")

    # "是" 在值中间
    r = p.parse("单位：某某是公司")
    d = p.to_variable_dict(r)
    print(f"    '单位：某某是公司' -> {d}")
    # 期望：单位="某某是公司"（第一个分隔符）
    test("'是'在值中间保留", d.get("单位") == "某某是公司", f"实际: {d.get('单位')}")

    # 多个分隔符取第一个
    r = p.parse("姓名：张三:李四")
    d = p.to_variable_dict(r)
    print(f"    '姓名：张三:李四' -> {d}")
    test("多分隔符取第一个", d.get("姓名") == "张三:李四", f"实际: {d.get('姓名')}")


def test_address_splitting():
    print("\n--- 地址被拆分问题 ---")
    p = SmartParser()

    # 地址含空格会被 _preprocess 拆分
    r = p.parse("江西省赣州市 章贡区 红旗大道123号")
    d = p.to_variable_dict(r)
    print(f"    含空格地址 -> {d}")
    # 地址可能被拆成多个片段，无法正确识别
    has_address = "地址" in d
    test("含空格地址识别", has_address, f"实际字段: {list(d.keys())}")

    # 地址含逗号
    r = p.parse("江西省赣州市,章贡区,红旗大道123号")
    d = p.to_variable_dict(r)
    print(f"    含逗号地址 -> {d}")
    test("含逗号地址识别", "地址" in d, f"实际字段: {list(d.keys())}")

    # 地址含顿号
    r = p.parse("江西省赣州市、章贡区、红旗大道123号")
    d = p.to_variable_dict(r)
    print(f"    含顿号地址 -> {d}")
    test("含顿号地址识别", "地址" in d, f"实际字段: {list(d.keys())}")


def test_date_normalization():
    print("\n--- 日期归一化边界 ---")
    p = SmartParser()

    # KV 形式的日期是否归一化
    r = p.parse("申请日期：20261016")
    d = p.to_variable_dict(r)
    print(f"    KV申请日期 -> {d}")
    # 检查申请日期是否被归一化为 YYYY-MM-DD
    val = d.get("申请日期", "")
    test("KV日期归一化", val == "2026-10-16", f"实际: {val}")

    # 出生日期
    r = p.parse("出生日期：19900101")
    d = p.to_variable_dict(r)
    val = d.get("出生日期", "")
    test("出生日期归一化", val == "1990-01-01", f"实际: {val}")

    # 纯数字日期作为普通片段
    r = p.parse("20261016")
    d = p.to_variable_dict(r)
    val = d.get("日期", "")
    test("普通片段日期归一化", val == "2026-10-16", f"实际: {val}")


def test_expression_edge_cases():
    print("\n--- 表达式边界 ---")

    # 中文字符变量名
    try:
        result = evaluate("姓名 + '你好'", {"姓名": "张三"})
        test("中文变量名", result == "张三你好", f"实际: {result}")
    except Exception as e:
        record_bug("expression", f"中文变量名异常: {e}")

    # 嵌套函数
    try:
        result = evaluate("trim(concat('  ', substr('12345678', 2, 3)))", {})
        test("嵌套函数", result == "345", f"实际: {result}")
    except Exception as e:
        record_bug("expression", f"嵌套函数异常: {e}")

    # 除零
    try:
        result = evaluate("1 / 0", {})
        test("除零不崩溃", False, f"实际返回: {result}")
    except ExpressionError:
        test("除零抛ExpressionError", True)
    except Exception as e:
        record_bug("expression", f"除零异常类型不对: {type(e).__name__}: {e}")

    # 空表达式
    result = evaluate("", {})
    test("空表达式返回空", result == "", f"实际: {result}")

    # None 表达式
    result = evaluate(None, {})
    test("None表达式返回空", result == "", f"实际: {result}")

    # try_evaluate 对非表达式
    result = try_evaluate("普通文本", {})
    test("try_evaluate普通文本", result == "普通文本", f"实际: {result}")

    # is_expression 对纯数字
    test("纯数字不是表达式", not is_expression("123"))
    test("纯数字字符串不是表达式", not is_expression("3.14"))


def test_renderer_edge_cases():
    print("\n--- 渲染器边界 ---")
    from core.renderer import render_document, _replace_in_text

    # 变量值为 None
    result = _replace_in_text("{{姓名}}", {"姓名": None})
    test("None值渲染为None", result == "None", f"实际: {result}")

    # 变量值为数字
    result = _replace_in_text("{{数量}}", {"数量": 0})
    test("数字0渲染", result == "0", f"实际: {result}")

    # 变量值为布尔
    result = _replace_in_text("{{标志}}", {"标志": True})
    test("布尔值渲染", result == "True", f"实际: {result}")

    # 文本中无变量
    result = _replace_in_text("普通文本", {"姓名": "张三"})
    test("无变量文本不变", result == "普通文本", f"实际: {result}")

    # 多个相同变量
    result = _replace_in_text("{{姓名}}{{姓名}}", {"姓名": "张三"})
    test("重复变量", result == "张三张三", f"实际: {result}")

    # 变量标记嵌套（不支持，但不应崩溃）
    result = _replace_in_text("{{外{{内}}}}", {"内": "值", "外值": "x"})
    test("嵌套标记不崩溃", True)


def test_scanner_edge_cases():
    print("\n--- 扫描器边界 ---")

    # 变量名含中文
    vars1 = extract_variables_from_text("{{姓名}} ${身份证号}")
    test("中文变量名", "姓名" in vars1 and "身份证号" in vars1, f"实际: {vars1}")

    # 变量名含数字
    vars2 = extract_variables_from_text("{{变量1}} ${var_2}")
    test("变量名含数字", "变量1" in vars2 and "var_2" in vars2, f"实际: {vars2}")

    # 重命名
    text = "{{姓名}} {{客户名}}"
    renamed = rename_variables_in_text(text, {"姓名": "客户名"})
    test("重命名变量", renamed == "{{客户名}} {{客户名}}", f"实际: {renamed}")

    # ${} 重命名保持格式
    text2 = "${姓名} ${手机号}"
    renamed2 = rename_variables_in_text(text2, {"姓名": "客户名"})
    test("${}重命名保持格式", "${客户名}" in renamed2, f"实际: {renamed2}")

    # 空文本
    vars3 = extract_variables_from_text("")
    test("空文本无变量", len(vars3) == 0)

    # None
    vars4 = extract_variables_from_text(None)
    test("None无变量", len(vars4) == 0)


def test_parser_more_edge_cases():
    print("\n--- Parser 更多边界 ---")
    p = SmartParser()

    # 姓名是单字（不匹配2-4规则）
    r = p.parse("张")
    d = p.to_variable_dict(r)
    test("单字姓名不识别", "姓名" not in d, f"实际: {d}")

    # 姓名5个字
    r = p.parse("欧阳一二三")
    d = p.to_variable_dict(r)
    test("5字姓名不识别", "姓名" not in d, f"实际: {d}")

    # 手机号带横线
    r = p.parse("138-1234-5678")
    d = p.to_variable_dict(r)
    print(f"    带横线手机号 -> {d}")
    # 当前规则不支持带横线手机号，检查是否不崩溃
    test("带横线手机号不崩溃", r is not None)

    # 身份证15位（旧版）
    r = p.parse("360700900101123")
    d = p.to_variable_dict(r)
    print(f"    15位身份证 -> {d}")
    test("15位身份证不匹配18位规则", "身份证号" not in d, f"实际: {d}")

    # 项目编号
    r = p.parse("12345678901234")  # 14位
    d = p.to_variable_dict(r)
    test("14位项目编号", d.get("项目编号") == "12345678901234", f"实际: {d.get('项目编号')}")

    # 项目编号和日期冲突（14位数字既是项目编号又是日期？）
    # 20261016010101 是14位，匹配项目编号
    r = p.parse("20261016010101")
    d = p.to_variable_dict(r)
    print(f"    14位数字 -> {d}")
    # 项目编号优先级4，日期优先级5，所以应匹配项目编号
    test("14位优先项目编号", d.get("项目编号") == "20261016010101", f"实际: {d}")


def test_variable_manager_edge():
    print("\n--- 变量管理器边界 ---")

    # 空变量名
    vm = VariableManager("test")
    vm.init_from_template_vars(["正常变量", ""])
    test("空变量名被忽略", "" not in vm.variables, f"实际: {list(vm.variables.keys())}")

    # 重复变量名
    vm2 = VariableManager("test")
    vm2.init_from_template_vars(["A", "A", "A"])
    test("重复变量名去重", len(vm2.variables) == 1, f"实际: {len(vm2.variables)}")

    # 删除模板变量（应不允许）
    vm3 = VariableManager("test")
    vm3.init_from_template_vars(["模板变量"])
    vm3.remove_variable("模板变量")
    test("模板变量不可删除", "模板变量" in vm3.variables)

    # 删除自定义变量
    vm3.add_custom_variable("自定义", "值")
    vm3.remove_variable("自定义")
    test("自定义变量可删除", "自定义" not in vm3.variables)

    # get_value 不存在的变量
    test("不存在变量返回空", vm3.get_value("不存在") == "")

    # set_value 不存在的变量（应不添加）
    vm3.set_value("不存在", "值")
    test("set_value不添加新变量", "不存在" not in vm3.variables)


def main():
    print("=" * 60)
    print("第二轮深度测试")
    print("=" * 60)

    test_kv_edge_cases()
    test_address_splitting()
    test_date_normalization()
    test_expression_edge_cases()
    test_renderer_edge_cases()
    test_scanner_edge_cases()
    test_parser_more_edge_cases()
    test_variable_manager_edge()

    print("\n" + "=" * 60)
    print(f"第二轮结果：通过 {passed}，失败 {failed}，发现 Bug {len(bugs)}")
    print("=" * 60)

    if bugs:
        print("\n--- Bug 列表 ---")
        for i, (module, desc, detail) in enumerate(bugs, 1):
            print(f"\n[{i}] [{module}] {desc}")
            if detail:
                print(f"    {detail[:200]}")

    return len(bugs) == 0 and failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

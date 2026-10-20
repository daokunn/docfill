"""名单核心逻辑验证：持久化、主键合并、冲突保护、重名处理。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.roster import (
    STATUS_GENERATED,
    STATUS_PENDING,
    STATUS_READY,
    load_roster,
    roster_path,
)
from core import table_import

TMP = tempfile.mkdtemp(prefix="docfill_roster_test_")
ROSTER_FILE = os.path.join(TMP, "roster_公务卡申请.json")
REQUIRED = ["姓名", "身份证号", "贷款金额"]


def check(label, condition, extra=""):
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  -> {extra}" if extra else ""))
    return condition


failures = 0


def expect(label, condition, extra=""):
    global failures
    if not check(label, condition, extra):
        failures += 1


print("=== 1. 首次导入：建立 100 人名单（姓名+身份证，贷款金额留空）===")
roster = load_roster("公务卡申请", key_field="姓名", storage_path=ROSTER_FILE)
expect("初始为空", len(roster.rows) == 0)

first_batch = [
    {"姓名": f"客户{i}", "身份证号": f"3607001990010{i:05d}", "贷款金额": ""}
    for i in range(100)
]
result = roster.merge_rows(first_batch)
expect("新增 100 人", len(result.added) == 100, f"实际 {len(result.added)}")
expect("无冲突", not result.conflicts)
expect("无重名", not result.ambiguous)
roster.refresh_status(REQUIRED)
counts = roster.counts(REQUIRED)
expect("全部待补充", counts["pending"] == 100, str(counts))
expect("缺失项含贷款金额",
       roster.rows[0].missing_fields(REQUIRED) == ["贷款金额"],
       str(roster.rows[0].missing_fields(REQUIRED)))

print("\n=== 2. 持久化：关掉再打开，数据还在 ===")
expect("保存成功", roster.save())
expect("文件已生成", os.path.exists(ROSTER_FILE))

reloaded = load_roster("公务卡申请", storage_path=ROSTER_FILE)
expect("重载 100 行", len(reloaded.rows) == 100, f"实际 {len(reloaded.rows)}")
expect("主键被记住", reloaded.key_field == "姓名", reloaded.key_field)
expect("列被记住", reloaded.columns == ["姓名", "身份证号", "贷款金额"], str(reloaded.columns))
expect("值被记住", reloaded.rows[5].values["姓名"] == "客户5")
expect("重载后无读取错误", reloaded.load_error is None, str(reloaded.load_error))

print("\n=== 3. 第二批导入：只有身份证号+贷款金额，按姓名匹配不上 ===")
# 模拟真实场景：贷款金额表里没有姓名列，只有身份证号
second_batch = [
    {"身份证号": f"3607001990010{i:05d}", "贷款金额": f"{50000 + i}"}
    for i in range(60)
]
result2 = reloaded.merge_rows(second_batch, match_field="身份证号")
expect("用身份证号匹配成功，更新 60 人", len(result2.updated) == 60,
       f"实际更新 {len(result2.updated)}，缺主键 {len(result2.no_key)}")
expect("没有新增（不是重复建人）", len(result2.added) == 0, f"实际新增 {len(result2.added)}")
expect("姓名没被清空", reloaded.rows[0].values.get("姓名") == "客户0",
       str(reloaded.rows[0].values))
expect("贷款金额已填入", reloaded.rows[0].values.get("贷款金额") == "50000",
       str(reloaded.rows[0].values.get("贷款金额")))
expect("第 60 行仍为空", not reloaded.rows[60].values.get("贷款金额"),
       str(reloaded.rows[60].values.get("贷款金额")))

reloaded.refresh_status(REQUIRED)
counts2 = reloaded.counts(REQUIRED)
expect("60 人已填完", counts2["ready"] == 60, str(counts2))
expect("40 人待补充", counts2["pending"] == 40, str(counts2))

print("\n=== 4. 空值不得清除已有数据 ===")
result3 = reloaded.merge_rows([{"姓名": "客户0", "身份证号": "", "贷款金额": ""}])
expect("匹配到客户0", len(result3.updated) + result3.unchanged == 1)
expect("身份证号仍在", reloaded.rows[0].values.get("身份证号") == "360700199001000000",
       str(reloaded.rows[0].values))
expect("贷款金额仍在", reloaded.rows[0].values.get("贷款金额") == "50000")

print("\n=== 5. 冲突保护：导入不同的值，不静默覆盖 ===")
result4 = reloaded.merge_rows([
    {"姓名": "客户0", "贷款金额": "999999"},
    {"身份证号": "360700199001000001", "贷款金额": "888"},
], match_field="姓名")
expect("报告 1 处冲突", len(result4.conflicts) == 1, str(result4.conflicts))
expect("原值未被覆盖", reloaded.rows[0].values.get("贷款金额") == "50000",
       str(reloaded.rows[0].values.get("贷款金额")))
if result4.conflicts:
    conflict = result4.conflicts[0]
    expect("冲突信息完整",
           conflict["field"] == "贷款金额" and conflict["current"] == "50000"
           and conflict["incoming"] == "999999", str(conflict))

print("\n=== 5b. 用户明确要求覆盖时，才覆盖 ===")
result5 = reloaded.merge_rows(
    [{"姓名": "客户0", "贷款金额": "999999"}], overwrite_conflicts=True)
expect("覆盖生效", reloaded.rows[0].values.get("贷款金额") == "999999",
       str(reloaded.rows[0].values.get("贷款金额")))
expect("无冲突报告", not result5.conflicts)
reloaded.set_value(0, "贷款金额", "50000")  # 还原

print("\n=== 6. 重名：必须一并显示，不能瞎猜 ===")
roster6 = load_roster("重名测试", storage_path=os.path.join(TMP, "r6.json"))
roster6.merge_rows([
    {"姓名": "张三", "身份证号": "360700199001011111"},
    {"姓名": "张三", "身份证号": "360700199001012222"},
    {"姓名": "李四", "身份证号": "360700199001013333"},
])
duplicates = roster6.duplicate_keys()
expect("检测到重名", "张三" in duplicates, str(duplicates))
expect("重名定位到 2 行", duplicates.get("张三") == [0, 1], str(duplicates.get("张三")))
expect("李四不算重名", "李四" not in duplicates)

result6 = roster6.merge_rows([{"姓名": "张三", "贷款金额": "12345"}])
expect("重名行进入 ambiguous", len(result6.ambiguous) == 1, str(result6.ambiguous))
expect("重名时没有乱填", not roster6.rows[0].values.get("贷款金额"),
       str(roster6.rows[0].values))
expect("重名时没有乱填(第二行)", not roster6.rows[1].values.get("贷款金额"))
expect("摘要提到重名", "重名" in result6.summary(), result6.summary())
expect("明细给出定位指引", any("搜索" in line for line in result6.detail_lines()),
       str(result6.detail_lines()[-3:]))

print("\n=== 6b. 同一批文件里两个同名的人，各自成行，不合并成一个人 ===")
roster6b = load_roster("批内重名", storage_path=os.path.join(TMP, "r6b.json"))
result6b = roster6b.merge_rows([
    {"姓名": "王五", "身份证号": "111"},
    {"姓名": "王五", "身份证号": "222"},
])
expect("两人都新增", len(result6b.added) == 2, f"新增 {len(result6b.added)}")
expect("名单里有 2 行", len(roster6b.rows) == 2, f"实际 {len(roster6b.rows)}")
expect("两人身份证号不同",
       roster6b.rows[0].values.get("身份证号") == "111"
       and roster6b.rows[1].values.get("身份证号") == "222",
       str([r.values for r in roster6b.rows]))
expect("重名被 duplicate_keys 检出", "王五" in roster6b.duplicate_keys(),
       str(roster6b.duplicate_keys()))

print("\n=== 7. 缺主键的行：报出来，不丢 ===")
result7 = roster6.merge_rows([
    {"姓名": "", "贷款金额": "777"},
    {"身份证号": "360700199001013333", "贷款金额": "666"},
])
expect("缺主键 2 行", len(result7.no_key) == 2, f"实际 {len(result7.no_key)}")
expect("李四没被误填", not roster6.rows[2].values.get("贷款金额"))

print("\n=== 8. 搜索与筛选 ===")
hits = roster6.search("张三")
expect("按姓名搜到 2 行", hits == [0, 1], str(hits))
hits2 = roster6.search("360700199001012222")
expect("按身份证号搜到 1 行", hits2 == [1], str(hits2))
expect("空关键词返回全部", len(roster6.search("")) == len(roster6.rows))
expect("搜不到返回空", roster6.search("不存在的人") == [])

print("\n=== 9. 可选变量不算缺失 ===")
roster9 = load_roster("可选测试", storage_path=os.path.join(TMP, "r9.json"))
roster9.merge_rows([{"姓名": "赵六", "备注": ""}])
required9 = roster9.required_fields(["姓名", "备注"], ["备注"])
expect("必填项排除可选变量", required9 == ["姓名"], str(required9))
roster9.refresh_status(required9)
expect("备注空着也算已填完", roster9.rows[0].status == STATUS_READY, roster9.rows[0].status)

print("\n=== 10. 生成状态跟踪 ===")
roster9.mark_generated([0], {0: "D:/输出/公务卡申请_赵六"})
expect("标记为已生成", roster9.rows[0].status == STATUS_GENERATED)
expect("记录生成时间", bool(roster9.rows[0].generated_at), roster9.rows[0].generated_at)
expect("记录输出目录", roster9.rows[0].output_dir.startswith("D:/输出"))
roster9.refresh_status(required9)
expect("重算状态不会把已生成退回", roster9.rows[0].status == STATUS_GENERATED)
counts9 = roster9.counts(required9)
expect("统计正确", counts9 == {"total": 1, "pending": 0, "ready": 0, "generated": 1},
       str(counts9))
roster9.reset_generated([0])
expect("撤销生成标记", roster9.rows[0].status == STATUS_PENDING)

print("\n=== 11. 导出为批量生成的输入形状 ===")
exported = roster6.selected_dicts([0, 2])
expect("导出 2 行", len(exported) == 2, str(len(exported)))
expect("导出是 dict 列表", isinstance(exported[0], dict))
expect("导出含所有列", set(exported[0]) >= {"姓名", "身份证号", "贷款金额"},
       str(set(exported[0])))
table = roster6.to_table()
expect("导出表首行是表头", table[0] == roster6.columns, str(table[0]))
expect("导出表行数=数据行+1", len(table) == len(roster6.rows) + 1)

print("\n=== 12. 删除行 ===")
before = len(roster6.rows)
removed = roster6.remove_rows([0, 99])  # 越界下标要安全忽略
expect("删除 1 行", removed == 1 and len(roster6.rows) == before - 1,
       f"removed={removed}")

print("\n=== 13. 宽表读取 ===")
csv_path = os.path.join(TMP, "名单.csv")
with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
    handle.write("姓名,身份证号,贷款金额\n")
    handle.write("张三,360700199001011234,\n")
    handle.write("李四,360700199001015678,50000\n")
    handle.write("\n")  # 空行要跳过
    handle.write("王五,360700199001019012,30000\n")
header, rows, note, warns = table_import.read_table_file(csv_path)
expect("表头正确", header == ["姓名", "身份证号", "贷款金额"], str(header))
expect("读到 3 行（跳过空行）", len(rows) == 3, f"实际 {len(rows)}")
expect("CSV 文本无精度警告", warns == [], str(warns))
dicts = table_import.rows_to_dicts(header, rows)
expect("转 dict 正确", dicts[0]["姓名"] == "张三" and dicts[0]["贷款金额"] == "",
       str(dicts[0]))
expect("说明文字含分隔方式", "逗号" in note, note)

print("\n=== 13b. Excel 里身份证号存成文本时正确读取 ===")
xlsx_path = os.path.join(TMP, "名单.xlsx")
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["姓名", "身份证号", "贷款金额"])
ws.append(["张三", "360700199001011234", 50000])   # 文本存身份证号（正确做法）
ws.append(["李四", "360700199001015678", None])
wb.save(xlsx_path)
header_x, rows_x, note_x, warns_x = table_import.read_table_file(xlsx_path)
expect("Excel 表头正确", header_x == ["姓名", "身份证号", "贷款金额"], str(header_x))
expect("身份证号原样读出", rows_x[0][1] == "360700199001011234", repr(rows_x[0][1]))
expect("金额是整数字符串", rows_x[0][2] == "50000", repr(rows_x[0][2]))
expect("空单元格为空串", rows_x[1][2] == "", repr(rows_x[1][2]))
expect("文本身份证号无警告", warns_x == [], str(warns_x))

print("\n=== 13b2. Excel 里身份证号存成数值时必须警告（数据已损坏）===")
xlsx_bad = os.path.join(TMP, "名单_数值.xlsx")
wb2 = openpyxl.Workbook()
ws2 = wb2.active
ws2.append(["姓名", "身份证号"])
ws2.append(["张三", 360700199001011234])   # 数值存身份证号（用户常犯，会丢位）
wb2.save(xlsx_bad)
header_b, rows_b, note_b, warns_b = table_import.read_table_file(xlsx_bad)
expect("检测到精度丢失并警告", len(warns_b) == 1, str(warns_b))
expect("警告点名了身份证号列", any("身份证号" in w for w in warns_b), str(warns_b))
expect("警告给出解决办法", any("文本" in w for w in warns_b))

print("\n=== 13b3. CSV 里科学计数法号码必须警告 ===")
sci_path = os.path.join(TMP, "科学计数法.csv")
with open(sci_path, "w", encoding="utf-8", newline="") as handle:
    handle.write("姓名,身份证号\n张三,3.60700E+17\n")
header_sc, rows_sc, note_sc, warns_sc = table_import.read_table_file(sci_path)
expect("检测到科学计数法并警告", len(warns_sc) == 1, str(warns_sc))
expect("警告点名了身份证号列", any("身份证号" in w for w in warns_sc), str(warns_sc))

print("\n=== 13c. 分隔符自动识别（Excel 欧洲版用分号）===")
semi_path = os.path.join(TMP, "semi.csv")
with open(semi_path, "w", encoding="utf-8", newline="") as handle:
    handle.write("姓名;身份证号;贷款金额\n张三;111;\n")
header_s, rows_s, note_s, warns_s = table_import.read_table_file(semi_path)
expect("分号分隔识别成功", header_s == ["姓名", "身份证号", "贷款金额"], str(header_s))
expect("分号数据正确", rows_s[0][0] == "张三", str(rows_s[0]))

print("\n=== 13d. 表头映射到模板变量名 ===")
from core.field_mapper import match_template_variable
mapping = table_import.map_header_to_variables(
    ["证件号", "名字", "额外备注"],
    ["身份证号", "姓名"],
    normalize=match_template_variable)
expect("证件号 -> 身份证号", mapping.get("证件号") == "身份证号", str(mapping))
expect("额外备注保持原样", mapping.get("额外备注") == "额外备注", str(mapping))

print("\n=== 13e. 错误处理 ===")
for label, path in [("不存在的文件", os.path.join(TMP, "没有这个.csv")),
                    ("不支持的类型", os.path.join(TMP, "x.pdf"))]:
    try:
        if not os.path.exists(path):
            open(path, "w").close()
        table_import.read_table_file(path)
        expect(f"{label}应报错", False, "没有抛异常")
    except table_import.TableImportError as exc:
        expect(f"{label}报错友好", bool(str(exc)), str(exc))

print("\n=== 14. 名单文件损坏不能让软件崩 ===")
broken_path = os.path.join(TMP, "broken.json")
with open(broken_path, "w", encoding="utf-8") as handle:
    handle.write("{ 这不是合法 JSON")
broken = load_roster("坏文件", storage_path=broken_path)
expect("损坏时返回空名单", len(broken.rows) == 0)
expect("损坏原因被记录", broken.load_error is not None, str(broken.load_error))

print("\n=== 15. 业务名含非法字符也能存 ===")
safe = roster_path('公务/卡:申请*"测试')
expect("路径不含非法字符", not any(c in os.path.basename(safe) for c in '\\/:*?"<>|'),
       os.path.basename(safe))
expect("不同业务名不同文件",
       roster_path("业务A") != roster_path("业务B"))

print("\n=== 16. 报告文本 ===")
print(result4.summary())
for line in result4.detail_lines()[:6]:
    print(line)
result_all = roster6.merge_rows([
    {"姓名": "张三", "贷款金额": "1"},
    {"姓名": "", "贷款金额": "2"},
])
print("\n综合报告:", result_all.summary())

print("\n" + "=" * 50)
print(f"失败项: {failures}")
print("ALL PASS" if failures == 0 else "有失败项，需修复")
sys.exit(1 if failures else 0)

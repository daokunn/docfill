"""
智能文本解析模块（内网离线版）
职责：
  输入原始粘贴文本，输出识别字段结果。
  完全基于本地规则库模式匹配，不调用任何外部 API。
  支持正则规则 + 简易键值对识别（姓名：张三）。
  可单独单元测试。
"""

import datetime
import json
import os
import re
from typing import Dict, List, Optional, Tuple

from core.address_parser import AddressParser
from core.date_format import is_date_field
from core.field_mapper import CANONICAL_DATE_FIELDS, canonical_field
from core.rule_store import (
    USER_RULES_FILE,
    USER_SOURCE,
    compile_like_parser,
    load_user_rules,
    rules_for_business,
)

from app_paths import config_path

# 识别规则文件：优先读取 exe 同目录 config/rules.json（可外置自定义），否则使用 exe 内置资源
RULES_FILE = config_path("rules.json")


class ParsedField:
    """单个识别结果字段"""

    def __init__(self, field: str, value: str, label: str = "",
                 source: str = "rule", conflict: bool = False):
        """单个识别字段"""
        self.field = field            # 变量名（映射后为模板变量名）
        self.value = value            # 识别值
        self.label = label or field   # 显示名
        self.source = source          # 识别来源：rule / kv / manual / address
        self.conflict = conflict      # 是否有冲突（同一字段匹配到多个值）
        self.alternatives: List[str] = []  # 冲突时的候选值列表
        self.mapped_from = ""         # 由哪个识别字段映射而来（如 开始日期 -> 开始时间）
        self.in_template = True       # 是否匹配到了当前模板变量

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "field": self.field,
            "value": self.value,
            "label": self.label,
            "source": self.source,
            "conflict": self.conflict,
            "alternatives": self.alternatives,
            "mapped_from": self.mapped_from,
            "in_template": self.in_template,
        }


class ParseResult:
    """解析结果：包含识别字段、未识别片段、冲突字段"""

    def __init__(self):
        """初始化空的解析结果"""
        self.fields: List[ParsedField] = []   # 已识别字段列表
        self.unrecognized: List[str] = []     # 未识别片段（供人工确认）
        self.conflicts: List[str] = []        # 有冲突的字段名

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "fields": [f.to_dict() for f in self.fields],
            "unrecognized": self.unrecognized,
            "conflicts": self.conflicts,
        }

    @property
    def field_count(self) -> int:
        """已识别字段数量"""
        return len(self.fields)


class SmartParser:
    """智能文本解析器"""

    # 日期部分：8位数字 或 年-月-日 / 年/月/日 / 年月日
    _DATE_PART = r"(?:\d{8}|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)"
    # 时间段分隔符：- ~ 至 到 — –
    _RANGE_SEP = r"\s*[-~至到—–]\s*"
    _RANGE_PATTERN = re.compile(
        r"(" + _DATE_PART + r")" + _RANGE_SEP + r"(" + _DATE_PART + r")"
    )

    def __init__(self, rules_path: str = RULES_FILE, business_name: str = "",
                 user_rules_path: Optional[str] = None):
        """加载内置规则 + 用户自定义规则、预编译正则、初始化地址解析器。

        :param business_name: 当前业务名，用于筛选只对该业务生效的用户规则
        :param user_rules_path: 用户规则文件路径，默认取 config/user_rules.json
        """
        self.business_name = str(business_name or "")
        self.rules: List[dict] = []                # 正则规则列表（内置 + 用户）
        self.kv_separators: List[str] = ["：", ":", "=", "是"]  # 键值对分隔符
        self.rule_errors: List[str] = []           # 无法编译的规则说明，供界面提示
        self._load_rules(rules_path)
        self._load_user_rules(user_rules_path)
        self.address_parser = AddressParser()      # 地址解析器
        self._compile_rules()

    def _load_rules(self, path: str) -> None:
        """从 rules.json 加载识别规则和键值对分隔符"""
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.rules = data.get("rules", [])
            self.kv_separators = data.get("kv_separators", self.kv_separators)
        except (json.JSONDecodeError, IOError):
            pass

    def _load_user_rules(self, path: Optional[str]) -> None:
        """加载对当前业务生效的用户规则，追加到内置规则之后。

        用户规则由界面的「配置识别规则」写入 config/user_rules.json，
        软件升级不会覆盖，可手动备份或共享给同事。
        """
        if path is None:
            path = USER_RULES_FILE
        user_rules = rules_for_business(load_user_rules(path), self.business_name)
        for rule in user_rules:
            rule.setdefault("source", USER_SOURCE)
        self.rules.extend(user_rules)

    def _compile_rules(self) -> None:
        """预编译全部规则，并按「用户规则优先、组内优先级高的在前」排序。

        语法非法的规则不再静默跳过：以前是 except re.error: continue，
        用户写错一个括号，规则被悄悄丢弃且无任何提示，排查起来很费劲。
        现在记录到 self.rule_errors，由界面展示。
        """
        self._compiled_rules = []
        self.rule_errors = []
        for rule in self.rules:
            pattern = str(rule.get("pattern", ""))
            try:
                compiled = compile_like_parser(pattern)
            except re.error as exc:
                field = str(rule.get("field", "")) or "未知变量"
                source = "用户规则" if rule.get("source") == USER_SOURCE else "内置规则"
                self.rule_errors.append(
                    f"{source}「{field}」的正则无法编译：{exc.msg or exc}")
                continue
            self._compiled_rules.append((rule, compiled))

        # 用户规则整体优先于内置规则：内置的宽松模式（如「2-4 个汉字=姓名」）
        # 会先抢走值，导致用户专门为某个变量写的精确正则永远不生效。
        # 同组内按 priority 升序，数字越小优先级越高。
        self._compiled_rules.sort(key=lambda item: (
            0 if item[0].get("source") == USER_SOURCE else 1,
            item[0].get("priority", 99),
        ))

    def _preprocess(self, text: str) -> List[str]:
        """
        文本预处理：
        1. 按换行拆分为多行
        2. 每行按空格/逗号/顿号/分号进一步拆分
        3. 去除空片段
        """
        fragments: List[str] = []
        for line in (text or "").splitlines():
            # 先尝试键值对识别（整行可能是 姓名：张三）
            kv = self._detect_kv(line.strip())
            if kv:
                # 键值对作为整体片段，值部分单独处理
                key, value = kv
                fragments.append(f"__KV__:{key}:{value}")
                continue
            # 按分隔符拆分
            parts = re.split(r"[\s,，、;；]+", line.strip())
            for p in parts:
                p = p.strip()
                if p:
                    fragments.append(p)
        return fragments

    def _detect_kv(self, text: str) -> Optional[Tuple[str, str]]:
        """
        简易键值对识别：姓名：张三
        :return: (key, value) 或 None
        """
        for sep in self.kv_separators:
            if sep in text:
                idx = text.find(sep)
                key = text[:idx].strip()
                value = text[idx + len(sep):].strip()
                if key and value:
                    return (key, value)
        return None

    def _match_rule(self, fragment: str) -> Optional[Tuple[dict, str]]:
        """
        对片段依次尝试所有规则（按优先级从高到低）。
        :return: (rule, matched_value) 或 None
        """
        for rule, compiled in self._compiled_rules:
            if compiled.match(fragment):
                return (rule, fragment)
        return None

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """
        将各种日期格式归一化为 YYYY-MM-DD。
        支持：20260101 / 2026-01-01 / 2026/1/1 / 2026年1月1日
        非法日期（如 20260001、2026-02-30）原样返回，避免把编号改成假日期。
        """
        s = date_str.strip()
        # 8位纯数字：20260101
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
        if m:
            return SmartParser._validated_iso(m.group(1), m.group(2), m.group(3), s)
        # 年-月-日 / 年/月/日 / 年月日
        m = re.fullmatch(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", s)
        if m:
            return SmartParser._validated_iso(m.group(1), m.group(2), m.group(3), s)
        return s  # 无法识别则原样返回

    @staticmethod
    def _validated_iso(year: str, month: str, day: str, original: str) -> str:
        """校验日期是否真实存在，合法则返回 ISO 格式。"""
        try:
            value = datetime.date(int(year), int(month), int(day))
        except ValueError:
            return original
        return value.strftime("%Y-%m-%d")

    def _extract_date_ranges(self, text: str, result: ParseResult) -> str:
        """
        检测文本中的时间段（如 20260101-20261030），拆分为开始日期和结束日期。
        :return: 移除时间段后的文本
        """
        if not text:
            return text

        def _replacer(m: re.Match) -> str:
            start_raw, end_raw = m.group(1), m.group(2)
            start = self._normalize_date(start_raw)
            end = self._normalize_date(end_raw)
            # 开始日期、结束日期、起止日期（整个时间段）
            for field, value in [("开始日期", start), ("结束日期", end),
                                 ("起止日期", f"{start}~{end}")]:
                result.fields.append(ParsedField(
                    field=field, value=value, label=field, source="range"))
            return " "  # 用空格替换，避免后续被拆成单个日期

        return self._RANGE_PATTERN.sub(_replacer, text)

    def parse(self, text: str) -> ParseResult:
        """
        解析原始文本，返回 ParseResult。
        流程：时间段检测 -> 预处理 -> 逐片段匹配 -> 地址二次解析 -> 冲突处理
        """
        result = ParseResult()

        # 1. 先检测时间段（如 20260101-20261030），拆分为开始/结束日期
        text = self._extract_date_ranges(text, result)

        # 2. 预处理 + 逐片段匹配
        fragments = self._preprocess(text)

        # field_name -> list of values（用于冲突检测）
        field_values: Dict[str, List[str]] = {}

        for frag in fragments:
            # 处理键值对片段
            if frag.startswith("__KV__:"):
                parts = frag.split(":", 2)
                if len(parts) == 3:
                    key, value = parts[1], parts[2]
                    # 尝试用 key 匹配规则的 field 或 label
                    matched_rule = self._match_kv_key(key)
                    if matched_rule:
                        field = matched_rule["field"]
                    else:
                        field = key  # 未匹配到规则，直接用 key 作为变量名
                    field_values.setdefault(field, []).append(value)
                continue

            # 普通片段：尝试规则匹配
            matched = self._match_rule(frag)
            if matched:
                rule, value = matched
                field = rule["field"]
                field_values.setdefault(field, []).append(value)
            else:
                result.unrecognized.append(frag)

        # 生成 ParsedField 列表，处理冲突
        for field, values in field_values.items():
            # 找对应的 rule 获取 label
            label = field
            for rule in self.rules:
                if rule["field"] == field:
                    label = rule.get("label", field)
                    break

            if len(values) == 1:
                val = values[0]
                # 只对明确是日期/时间的字段做归一化，避免 8 位项目编号被改成假日期
                if is_date_field(field):
                    normalized = self._normalize_date(val)
                    if normalized != val:  # 归一化成功才使用
                        val = normalized
                result.fields.append(ParsedField(
                    field=field, value=val, label=label, source="rule"))
            else:
                # 冲突：取第一个，其余放入 alternatives
                pf = ParsedField(
                    field=field, value=values[0], label=label,
                    source="rule", conflict=True)
                pf.alternatives = values[1:]
                result.fields.append(pf)
                result.conflicts.append(field)

        # 地址二次解析：如果有"地址"字段，进一步拆分省/市/区
        for i, f in enumerate(result.fields):
            if f.field == "地址" and f.value:
                parsed_addr = self.address_parser.parse(f.value)
                # 按 省 -> 市 -> 区 的固定顺序插入，保证结果表顺序稳定
                insert_at = i + 1
                for sub_field in ["省", "市", "区"]:
                    if parsed_addr.get(sub_field):
                        result.fields.insert(insert_at, ParsedField(
                            field=sub_field, value=parsed_addr[sub_field],
                            label=sub_field, source="address"))
                        insert_at += 1
                # 更新地址字段为详细地址
                f.value = parsed_addr.get("详细地址", f.value)
                break

        return result

    def _match_kv_key(self, key: str) -> Optional[dict]:
        """键值对的 key 匹配规则的 field / label，并应用别名归一化。"""
        canonical = canonical_field(key)
        for rule in self.rules:
            if rule["field"] == canonical or rule.get("label") == canonical:
                return rule

        # 开始时间/结束时间等别名没有独立正则规则，但属于时间段语义
        if canonical in CANONICAL_DATE_FIELDS:
            return {"field": canonical, "label": key}
        return None

    def to_variable_dict(self, result: ParseResult) -> Dict[str, str]:
        """将解析结果转为变量字典（忽略冲突和未识别）"""
        return {f.field: f.value for f in result.fields}

    # 多人分隔符：--- 或 ===（独占一行）
    _MULTI_SEP = re.compile(r"^\s*[-=]{3,}\s*$", re.MULTILINE)
    # 空行：允许多个连续空行，前后可有空格
    _BLANK_LINE = re.compile(r"\n\s*\n")
    # 判断一个数据块是否像“一个人的资料”（仅用于空行模式的启用判断）
    _PERSON_HINT = re.compile(r"姓名|身份证|手机号|客户名|证件号|联系电话")

    def split_multi(self, text: str) -> List[str]:
        """
        将多人数据拆分为单人数据块。

        支持两种写法：
        1. 独占一行的 --- 或 ===（明确分隔）：始终拆分，不看块内内容
        2. 空行分隔：仅当至少两个数据块都含“姓名/身份证号”等字段名时启用，
           避免把单个人的多段文本误拆成多人

        裸文本（没有字段名）请用第 1 种写法明确分隔。空行模式的判据是字段名，
        裸文本里没有字段名，因此不会被自动拆分，会整体当作单人处理。
        """
        if not text:
            return []

        if self._MULTI_SEP.search(text):
            blocks = self._MULTI_SEP.split(text)
        else:
            blocks = self._BLANK_LINE.split(text)
            person_blocks = [b for b in blocks if b.strip() and self._PERSON_HINT.search(b)]
            if len(person_blocks) < 2:
                return [text.strip()]

        return [b.strip() for b in blocks if b.strip()]

    def parse_multi(self, text: str) -> List[ParseResult]:
        """
        解析多人数据，返回每人的 ParseResult 列表。
        用 --- 或 === 分隔不同的人。
        """
        blocks = self.split_multi(text)
        if not blocks:
            return []
        return [self.parse(b) for b in blocks]

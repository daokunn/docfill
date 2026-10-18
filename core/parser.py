"""
智能文本解析模块（内网离线版）
职责：
  输入原始粘贴文本，输出识别字段结果。
  完全基于本地规则库模式匹配，不调用任何外部 API。
  支持正则规则 + 简易键值对识别（姓名：张三）。
  可单独单元测试。
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple

from core.address_parser import AddressParser

from app_paths import config_path

# 识别规则文件：优先读取 exe 同目录 config/rules.json（可外置自定义），否则使用 exe 内置资源
RULES_FILE = config_path("rules.json")


class ParsedField:
    """单个识别结果字段"""

    def __init__(self, field: str, value: str, label: str = "",
                 source: str = "rule", conflict: bool = False):
        """单个识别字段"""
        self.field = field            # 变量名
        self.value = value            # 识别值
        self.label = label or field   # 显示名
        self.source = source          # 识别来源：rule（正则规则）/ kv（键值对）
        self.conflict = conflict      # 是否有冲突（同一字段匹配到多个值）
        self.alternatives: List[str] = []  # 冲突时的候选值列表

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "field": self.field,
            "value": self.value,
            "label": self.label,
            "source": self.source,
            "conflict": self.conflict,
            "alternatives": self.alternatives,
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

    def __init__(self, rules_path: str = RULES_FILE):
        """加载规则、预编译正则、初始化地址解析器"""
        self.rules: List[dict] = []                # 正则规则列表
        self.kv_separators: List[str] = ["：", ":", "=", "是"]  # 键值对分隔符
        self._load_rules(rules_path)
        self.address_parser = AddressParser()      # 地址解析器
        # 预编译正则
        self._compiled_rules = []
        for rule in self.rules:
            try:
                pattern = rule["pattern"]
                compiled = re.compile(r"^" + pattern.lstrip("^").rstrip("$") + r"$")
                self._compiled_rules.append((rule, compiled))
            except re.error:
                continue
        # 按优先级排序（数字越小越高）
        self._compiled_rules.sort(key=lambda x: x[0].get("priority", 99))

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
        """
        s = date_str.strip()
        # 8位纯数字：20260101
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        # 年-月-日 / 年/月/日 / 年月日
        m = re.fullmatch(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", s)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        return s  # 无法识别则原样返回

    @staticmethod
    def _is_date_field(field: str) -> bool:
        """判断字段名是否为日期相关字段"""
        return "日期" in field or "时间" in field

    @staticmethod
    def _looks_like_date(value: str) -> bool:
        """判断值是否看起来像日期（8位数字 或 年-月-日 格式）"""
        if not isinstance(value, str) or not value:
            return False
        s = value.strip()
        if re.fullmatch(r"\d{8}", s):
            return True
        if re.fullmatch(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?", s):
            return True
        return False

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
                # 日期字段归一化为 YYYY-MM-DD
                # 字段名包含"日期"或"时间"，或值看起来像日期时归一化
                if self._is_date_field(field) or self._looks_like_date(val):
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
        """键值对的 key 匹配规则的 field 或 label"""
        for rule in self.rules:
            if rule["field"] == key or rule.get("label") == key:
                return rule
        return None

    def to_variable_dict(self, result: ParseResult) -> Dict[str, str]:
        """将解析结果转为变量字典（忽略冲突和未识别）"""
        return {f.field: f.value for f in result.fields}

    # 多人分隔符：--- 或 ===（独占一行）
    _MULTI_SEP = re.compile(r"^\s*[-=]{3,}\s*$", re.MULTILINE)

    def split_multi(self, text: str) -> List[str]:
        """
        将多人数据拆分为单人数据块。
        分隔符：独占一行的 --- 或 ===
        单人内部用空行/换行分隔不同变量，不会与分隔符冲突。
        """
        if not text:
            return []
        blocks = self._MULTI_SEP.split(text)
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

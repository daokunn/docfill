"""变量校验引擎：生成前检查字段值是否合法。

设计（对齐用户诉求）：
  - 在【设置】里统一开关，默认开启；
  - 内置常见校验（身份证号含校验位、手机号、邮箱、数字、日期等），开箱即用；
  - 其他变量由用户自己写正则，配置方式与"识别规则"一致（按变量名配置）；
  - 规则按变量作用，支持全局 + 业务覆盖，存本机 JSON，升级不覆盖；
  - 校验只报告问题，不擅自修改任何值；空值跳过（交给原有的空变量检查）。

文件：config/user_validation_rules.json（可写，升级不覆盖）
结构：
{
  "global": {"身份证号": {"preset": "id_card", "regex": "", "message": "", "enabled": true}},
  "businesses": {"公务卡申请": {"经办人": {"regex": "^李", ...}}}
}
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app_paths import config_path

RULES_FILE = config_path("user_validation_rules.json", writable=True)

# 内置预设
PRESET_ID_CARD = "id_card"
PRESET_PHONE = "phone"
PRESET_EMAIL = "email"
PRESET_NUMBER = "number"
PRESET_DATE = "date"
PRESET_CUSTOM = "custom"

PRESET_LABELS = {
    PRESET_ID_CARD: "身份证号（18位 + 校验位）",
    PRESET_PHONE: "手机号（11位）",
    PRESET_EMAIL: "邮箱",
    PRESET_NUMBER: "纯数字/金额",
    PRESET_DATE: "日期（YYYY-MM-DD 等）",
    PRESET_CUSTOM: "自定义正则",
}

_FILE_NOTE = (
    "变量校验规则：生成前检查字段值是否合法。由界面【设置 → 变量校验】写入。"
    "预设为常见校验，也可为任意变量写自定义正则。软件升级不会覆盖本文件。"
)


@dataclass
class ValidationIssue:
    """一个校验问题。"""
    variable: str
    value: str
    message: str
    rule_scope: str = ""


def empty_document() -> Dict[str, Any]:
    return {"_说明": _FILE_NOTE, "global": {}, "businesses": {}}


def load_document() -> Dict[str, Any]:
    if not os.path.exists(RULES_FILE):
        return empty_document()
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return empty_document()
    if not isinstance(data, dict):
        return empty_document()
    data.setdefault("global", {})
    data.setdefault("businesses", {})
    if not isinstance(data["global"], dict):
        data["global"] = {}
    if not isinstance(data["businesses"], dict):
        data["businesses"] = {}
    return data


def save_document(data: Dict[str, Any]) -> bool:
    try:
        folder = os.path.dirname(RULES_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        payload = dict(data)
        payload.setdefault("_说明", _FILE_NOTE)
        tmp = RULES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, RULES_FILE)
    except OSError:
        return False
    return True


def normalize_rule(rule: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = {
        "preset": PRESET_CUSTOM,
        "regex": "",
        "message": "",
        "enabled": True,
    }
    if not isinstance(rule, dict):
        return result
    preset = str(rule.get("preset") or PRESET_CUSTOM)
    result["preset"] = preset if preset in PRESET_LABELS else PRESET_CUSTOM
    result["regex"] = str(rule.get("regex") or "")
    result["message"] = str(rule.get("message") or "")
    result["enabled"] = bool(rule.get("enabled", True))
    return result


def set_rule(doc: Dict[str, Any], variable: str, rule: Dict[str, Any],
             scope: str = "business", business_name: str = "") -> bool:
    """保存一条规则；会从另一作用域删除同名规则，避免重复。"""
    variable = str(variable or "").strip()
    if not variable:
        return False
    normalized = normalize_rule(rule)
    if scope == "global":
        doc.setdefault("global", {})[variable] = normalized
        biz = doc.setdefault("businesses", {})
        for item in biz.values():
            if isinstance(item, dict):
                item.pop(variable, None)
    else:
        biz = doc.setdefault("businesses", {})
        biz.setdefault(str(business_name or ""), {})[variable] = normalized
        doc.setdefault("global", {}).pop(variable, None)
    return True


def remove_rule(doc: Dict[str, Any], variable: str,
                scope: str = "business", business_name: str = "") -> None:
    variable = str(variable or "").strip()
    if scope == "global":
        doc.setdefault("global", {}).pop(variable, None)
    else:
        biz = doc.setdefault("businesses", {})
        rules = biz.get(str(business_name or ""))
        if isinstance(rules, dict):
            rules.pop(variable, None)


def merged_rules(doc: Dict[str, Any], business_name: str) -> Dict[str, Dict[str, Any]]:
    """对某业务生效的规则：全局 + 业务覆盖。"""
    merged: Dict[str, Dict[str, Any]] = {}
    global_rules = doc.get("global", {}) or {}
    if isinstance(global_rules, dict):
        for name, rule in global_rules.items():
            merged[str(name)] = normalize_rule(rule)
    biz = doc.get("businesses", {}) or {}
    if isinstance(biz, dict):
        rules = biz.get(str(business_name or ""), {})
        if isinstance(rules, dict):
            for name, rule in rules.items():
                merged[str(name)] = normalize_rule(rule)
    return merged


_ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK = "10X98765432"


def _is_valid_id_card(value: str) -> bool:
    s = value.strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", s):
        return False
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    return _ID_CHECK[total % 11] == s[17]


_PRESET_PATTERNS = {
    PRESET_PHONE: r"^1[3-9]\d{9}$",
    PRESET_EMAIL: r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    PRESET_NUMBER: r"^-?\d+(?:\.\d+)?$",
    PRESET_DATE: r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$|^\d{8}$",
}


def validate_value(value: Any, rule: Dict[str, Any]) -> str:
    """校验单个值，返回错误提示；合法或跳过时返回空串。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:  # 空值交给空变量检查处理
        return ""

    rule = normalize_rule(rule)
    if not rule["enabled"]:
        return ""

    preset = rule["preset"]
    message = rule["message"].strip()

    if preset == PRESET_ID_CARD:
        ok = _is_valid_id_card(text)
        return "" if ok else (message or "身份证号不合法（位数或校验位错误）")

    if preset == PRESET_CUSTOM:
        pattern = rule["regex"].strip()
        if not pattern:
            return ""
        try:
            compiled = re.compile(pattern)
        except re.error:
            return ""  # 非法正则忽略，由配置界面负责提示
        ok = bool(compiled.search(text))
        return "" if ok else (message or f"不符合规则：{pattern}")

    pattern = _PRESET_PATTERNS.get(preset)
    if not pattern:
        return ""
    ok = bool(re.fullmatch(pattern, text))
    return "" if ok else (message or f"格式不正确（{PRESET_LABELS.get(preset, preset)}）")


# 内置预设"开箱即用"：按变量名自动套用，用户无需先配置。
# 变量名 → 预设；同义名（身份证/证件号/联系电话…）由别名表归一后匹配。
_BUILTIN_BY_CANONICAL: Dict[str, str] = {
    "身份证号": PRESET_ID_CARD,
    "手机号": PRESET_PHONE,
    "邮箱": PRESET_EMAIL,
}


def _canonical_name(variable: str) -> str:
    """把同义变量名归一到标准名（身份证→身份证号、联系电话→手机号）。"""
    name = str(variable or "").strip()
    if not name:
        return ""
    try:
        from core.alias_mapper import get_alias_mapper
        canonical = get_alias_mapper().normalize(name)
        if canonical:
            return str(canonical)
    except Exception:
        pass
    # 别名表不可用时的兜底：有限常见同义词
    fallback = {
        "身份证": "身份证号", "证件号": "身份证号", "身份证号码": "身份证号",
        "手机": "手机号", "联系电话": "手机号", "电话号码": "手机号",
    }
    return fallback.get(name, name)


def default_rule_for_variable(variable: str) -> Optional[Dict[str, Any]]:
    """返回变量名的内置默认规则；没有则返回 None。"""
    canonical = _canonical_name(variable)
    preset = _BUILTIN_BY_CANONICAL.get(canonical)
    if not preset:
        return None
    return normalize_rule({"preset": preset, "enabled": True})


def effective_rules(doc: Dict[str, Any], business_name: str,
                    variable_names: Optional[List[str]] = None,
                    use_builtin: bool = True) -> Dict[str, Dict[str, Any]]:
    """实际生效规则 = 内置默认 + 用户显式规则（用户规则优先，含禁用）。"""
    rules: Dict[str, Dict[str, Any]] = {}
    if use_builtin:
        names = list(variable_names or [])
        for name in names:
            builtin = default_rule_for_variable(name)
            if builtin:
                rules[str(name)] = builtin
    # 用户显式规则覆盖（同变量名）
    for name, rule in merged_rules(doc, business_name).items():
        rules[name] = rule
    return rules


def collect_issues(values: Dict[str, Any], doc: Dict[str, Any],
                   business_name: str = "", enabled: bool = True,
                   use_builtin: bool = True,
                   variable_names: Optional[List[str]] = None) -> List[ValidationIssue]:
    """对一组变量值运行校验，返回所有问题。

    - use_builtin=True 时，身份证/手机号/邮箱等常见变量自动套内置预设，
      无需用户先在设置里配置（兑现"开箱即用"承诺）。
    - 用户显式规则（含 disabled）优先于内置默认。
    """
    if not enabled:
        return []
    # 未显式给变量名列表时，用本次待校验的键集合
    names = list(variable_names or values.keys())
    rules = effective_rules(doc, business_name, names, use_builtin=use_builtin)
    issues: List[ValidationIssue] = []
    for variable, rule in rules.items():
        if variable not in values:
            continue
        message = validate_value(values[variable], rule)
        if message:
            issues.append(ValidationIssue(
                variable=variable,
                value=str(values[variable] or ""),
                message=message,
                rule_scope=business_name if business_name else "global",
            ))
    return issues

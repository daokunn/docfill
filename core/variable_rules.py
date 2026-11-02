"""用户变量规则：默认值、公式、辅助变量。

文件：config/user_variable_rules.json（可写，升级不覆盖）

结构：
{
  "global": {"经办人": {"mode": "default", "expr": "小李", ...}},
  "businesses": {
    "公务卡申请": {
      "单位": {"mode": "default", "expr": "某某公司", "apply_on_empty": true},
      "出生日期": {"mode": "formula", "expr": "身份证号[6:14]", "decimals": 0},
      "期限月数": {"mode": "formula", "expr": "月数", "kind": "aux", "export_summary": true}
    }
  }
}

规则字段：
  mode: manual / default / formula
  expr: 默认值或公式（default 模式可写纯文本，也可写 today()）
  decimals: 小数位，默认 0；仅数值结果生效
  apply_on_empty: 名单/批量时，空白是否自动套用默认值
  export_summary: 辅助变量是否写入移交清单/汇总表
  kind: template / aux
  allow_override: 公式变量是否允许手动覆盖（默认否）
"""

import json
import os
from typing import Any, Dict, List, Optional

from app_paths import config_path

RULES_FILE = config_path("user_variable_rules.json", writable=True)

GLOBAL_SCOPE = "global"
BUSINESS_SCOPE = "business"

VALID_MODES = ("manual", "default", "formula")
VALID_KINDS = ("template", "aux")

RULE_DEFAULTS = {
    "mode": "manual",
    "expr": "",
    "decimals": 0,
    "apply_on_empty": True,
    "export_summary": False,
    "kind": "template",
    "allow_override": False,
}

_FILE_NOTE = (
    "用户变量规则：默认值/公式/辅助变量，由界面「变量默认值与计算」写入。"
    "软件升级不会覆盖本文件；可随配置包一起备份/恢复。"
)


def _empty_document() -> Dict[str, Any]:
    return {"_说明": _FILE_NOTE, "global": {}, "businesses": {}}


def load_document() -> Dict[str, Any]:
    """读取整个规则文件，损坏时返回空结构。"""
    if not os.path.exists(RULES_FILE):
        return _empty_document()
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return _empty_document()
    if not isinstance(data, dict):
        return _empty_document()
    data.setdefault("global", {})
    data.setdefault("businesses", {})
    if not isinstance(data["global"], dict):
        data["global"] = {}
    if not isinstance(data["businesses"], dict):
        data["businesses"] = {}
    return data


def save_document(data: Dict[str, Any]) -> bool:
    """原子写入规则文件。"""
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
    """补全/校正单个规则，避免界面写入脏数据。"""
    result = dict(RULE_DEFAULTS)
    if not isinstance(rule, dict):
        return result
    mode = str(rule.get("mode") or "manual")
    result["mode"] = mode if mode in VALID_MODES else "manual"
    kind = str(rule.get("kind") or "template")
    result["kind"] = kind if kind in VALID_KINDS else "template"
    result["expr"] = str(rule.get("expr") or "")
    try:
        decimals = int(rule.get("decimals", 0))
    except (TypeError, ValueError):
        decimals = 0
    result["decimals"] = max(0, min(6, decimals))
    result["apply_on_empty"] = bool(rule.get("apply_on_empty", True))
    result["export_summary"] = bool(rule.get("export_summary", False))
    result["allow_override"] = bool(rule.get("allow_override", False))
    return result


def _business_rules(data: Dict[str, Any], business_name: str) -> Dict[str, Dict[str, Any]]:
    businesses = data.get("businesses", {})
    rules = businesses.get(business_name, {})
    return rules if isinstance(rules, dict) else {}


def merged_rules(business_name: str, document: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """返回对某业务生效的规则：全局 + 业务覆盖，附带 _scope。"""
    data = document or load_document()
    merged: Dict[str, Dict[str, Any]] = {}
    global_rules = data.get("global", {}) or {}
    if isinstance(global_rules, dict):
        for name, rule in global_rules.items():
            normalized = normalize_rule(rule)
            normalized["_scope"] = GLOBAL_SCOPE
            merged[str(name)] = normalized
    for name, rule in _business_rules(data, business_name).items():
        normalized = normalize_rule(rule)
        normalized["_scope"] = BUSINESS_SCOPE
        merged[str(name)] = normalized
    return merged


def get_rule(business_name: str, variable: str,
             document: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """取某业务下某变量的最终规则。"""
    return merged_rules(business_name, document).get(variable, normalize_rule(None))


def set_rule(business_name: str, variable: str, rule: Dict[str, Any],
             scope: str = BUSINESS_SCOPE,
             document: Optional[Dict[str, Any]] = None) -> bool:
    """保存一条规则；会自动从另一作用域删除，避免重复。"""
    data = document or load_document()
    variable = str(variable or "").strip()
    if not variable:
        return False
    normalized = normalize_rule(rule)
    normalized.pop("_scope", None)
    if scope == GLOBAL_SCOPE:
        data.setdefault("global", {})[variable] = normalized
        _remove_from_business(data, business_name, variable)
    else:
        data.setdefault("businesses", {}).setdefault(business_name, {})[variable] = normalized
        data.setdefault("global", {}).pop(variable, None)
    return save_document(data)


def remove_rule(business_name: str, variable: str, scope: str = BUSINESS_SCOPE,
                document: Optional[Dict[str, Any]] = None) -> bool:
    """删除一条规则。"""
    data = document or load_document()
    variable = str(variable or "").strip()
    if scope == GLOBAL_SCOPE:
        data.setdefault("global", {}).pop(variable, None)
    else:
        _remove_from_business(data, business_name, variable)
    return save_document(data)


def _remove_from_business(data: Dict[str, Any], business_name: str, variable: str) -> None:
    businesses = data.setdefault("businesses", {})
    rules = businesses.get(business_name)
    if isinstance(rules, dict):
        rules.pop(variable, None)
        if not rules:
            businesses.pop(business_name, None)


def aux_names(business_name: str, document: Optional[Dict[str, Any]] = None) -> List[str]:
    """返回该业务声明的辅助变量名（不在模板里的计算变量）。"""
    names = []
    for name, rule in merged_rules(business_name, document).items():
        if rule.get("kind") == "aux":
            names.append(name)
    return names

"""用户自定义识别规则库。

职责：
  1. 读写 config/user_rules.json（用户规则，升级永不覆盖）
  2. 正则语法校验与危险写法静态检查
  3. 按业务作用域筛选规则
  4. 提供与解析器一致的编译方式，保证"试打"结果和真实解析行为相同

分层约定：
  - config/rules.json       内置规则，随软件升级可被覆盖
  - config/user_rules.json  用户规则，由界面写入，可手动备份/共享给同事

排序约定：用户规则始终优先于内置规则求值。用户规则是针对自己业务刻意写出来的，
比内置的通用模式（如"2-4 个汉字=姓名"、".*公司.*=单位"）更具体，应当先命中。
同一批用户规则内，后添加的优先——后写的通常是对前面的修正。
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app_paths import config_path

# 用户规则文件：固定放 exe 同目录 config/ 下，可写、可持久化
USER_RULES_FILE = config_path("user_rules.json", writable=True)

GLOBAL_SCOPE = "*"          # 作用域：全局生效
USER_SOURCE = "user"        # 规则来源：用户自定义
BUILTIN_SOURCE = "builtin"  # 规则来源：软件内置

DEFAULT_PRIORITY = 10
MAX_PATTERN_LENGTH = 500
MAX_SAMPLES = 10

_FILE_NOTE = (
    "用户自定义识别规则，由界面「配置识别规则」写入，软件升级不会覆盖本文件。"
    "scope 为 * 表示全局生效，否则为业务名。"
    "同一变量可以有多条 pattern，命中任意一条即算识别成功。"
    "可手动备份本文件，或复制到同事电脑的相同位置共享规则。"
)

# 嵌套量词（如 (a+)+、(\d{2,})*）可能触发灾难性回溯，把界面卡死
_NESTED_QUANTIFIER = re.compile(
    r"\([^()]*[+*][^()]*\)[+*{]"
    r"|\([^()]*\{\d+,\}[^()]*\)[+*{]"
)

# 最近一次读写规则文件的错误，供界面提示；None 表示没有错误
_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """返回最近一次读写规则文件的错误信息，没有则返回 None。"""
    return _last_error


def compile_like_parser(pattern: str) -> "re.Pattern[str]":
    """按解析器的同样方式编译规则：去掉首尾 ^ $，再强制整段匹配。

    core/parser.py 加载规则时就是这么处理的。规则编辑界面的"试打"必须调用
    本函数，否则界面显示的命中结果和真实解析行为会不一致，用户会被误导。
    """
    body = str(pattern or "").lstrip("^").rstrip("$")
    return re.compile(r"^" + body + r"$")


def validate_pattern(pattern: str) -> Tuple[bool, str]:
    """校验正则语法。返回 (是否合法, 错误说明)；合法时说明为空字符串。

    注意：解析器对非法正则是静默跳过的（见 parser.py 的 except re.error），
    用户写错一个括号就会以为规则生效了其实没有。本函数负责把错误暴露出来。
    """
    text = str(pattern or "").strip()
    if not text:
        return False, "正则不能为空"
    if len(text) > MAX_PATTERN_LENGTH:
        return False, f"正则过长（{len(text)} 字符），上限 {MAX_PATTERN_LENGTH} 字符"

    # 先校验用户写的原文，这样报错位置才对得上用户看到的字符
    try:
        re.compile(text)
    except re.error as exc:
        return False, _describe_syntax_error(exc, text)

    # 再校验加上整段匹配后的形式，避免 ^ $ 拼接产生新的语法问题
    try:
        compile_like_parser(text)
    except re.error as exc:
        return False, f"加上整段匹配后语法出错：{exc.msg or exc}"

    return True, ""


def _describe_syntax_error(exc: "re.error", text: str) -> str:
    """把 re.error 转成带位置的中文说明。"""
    message = str(exc.msg or exc)
    position = getattr(exc, "pos", None)
    if isinstance(position, int) and 0 <= position < len(text):
        return f"第 {position + 1} 个字符附近：{message}"
    return message


def check_pattern_safety(pattern: str) -> List[str]:
    """静态扫描可能拖慢界面或抢走其他变量值的写法，返回警告列表。

    只给警告不阻止保存——最终决定权在用户。
    """
    warnings: List[str] = []
    text = str(pattern or "").strip()
    if not text:
        return warnings

    if _NESTED_QUANTIFIER.search(text):
        warnings.append("检测到嵌套量词（形如 (a+)+），遇到长文本可能长时间无响应，建议改写")
    if text.count(".*") >= 3:
        warnings.append("包含多个 .* ，匹配范围过宽，可能抢走本该属于其他变量的值")
    if text in (".*", ".+", "^.*$", "^.+$"):
        warnings.append("这条正则会命中任意内容，其他变量将永远匹配不到")
    return warnings


def _normalize_rule(item: Dict[str, Any], field: str, pattern: str) -> Dict[str, Any]:
    """把文件里的规则补全成统一结构，容错处理缺字段和类型不对的情况。"""
    try:
        priority = int(item.get("priority", DEFAULT_PRIORITY))
    except (TypeError, ValueError):
        priority = DEFAULT_PRIORITY

    raw_samples = item.get("samples") or []
    if not isinstance(raw_samples, list):
        raw_samples = []
    samples = [str(s).strip() for s in raw_samples if str(s).strip()][:MAX_SAMPLES]

    return {
        "field": field,
        "pattern": pattern,
        "priority": priority,
        "label": str(item.get("label") or field),
        "description": str(item.get("description") or ""),
        "scope": str(item.get("scope") or GLOBAL_SCOPE),
        "source": USER_SOURCE,
        "samples": samples,
        "created_at": str(item.get("created_at") or ""),
    }


def load_user_rules(rules_path: str = USER_RULES_FILE) -> List[Dict[str, Any]]:
    """读取用户规则。文件不存在或损坏时返回空列表，并记录错误原因。

    损坏时不能抛异常：否则用户规则文件被写坏一次，整个软件就起不来了。
    但也不能像以前那样静默——错误记在 _last_error 里，由界面提示用户。
    """
    global _last_error
    _last_error = None

    if not os.path.exists(rules_path):
        return []
    try:
        with open(rules_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        _last_error = f"用户规则文件读取失败：{exc}"
        return []

    if not isinstance(data, dict):
        _last_error = "用户规则文件格式不正确（顶层应为对象）"
        return []

    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        _last_error = "用户规则文件中 rules 应为数组"
        return []

    rules: List[Dict[str, Any]] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field", "")).strip()
        pattern = str(item.get("pattern", "")).strip()
        if not field or not pattern:
            continue
        rules.append(_normalize_rule(item, field, pattern))
    return rules


def save_user_rules(rules: List[Dict[str, Any]], rules_path: str = USER_RULES_FILE) -> bool:
    """写入用户规则（先写临时文件再替换，避免写一半损坏原文件）。"""
    global _last_error
    payload = {"_说明": _FILE_NOTE, "rules": list(rules)}
    try:
        folder = os.path.dirname(rules_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp_path = rules_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, rules_path)
    except OSError as exc:
        _last_error = f"用户规则保存失败：{exc}"
        return False

    _last_error = None
    return True


def rules_for_business(rules: List[Dict[str, Any]], business: str) -> List[Dict[str, Any]]:
    """筛出对指定业务生效的用户规则：全局规则 + 该业务的专属规则。"""
    business = str(business or "").strip()
    result = []
    for rule in rules:
        scope = str(rule.get("scope") or GLOBAL_SCOPE)
        if scope == GLOBAL_SCOPE or (business and scope == business):
            result.append(rule)
    return result


def next_priority(rules: List[Dict[str, Any]]) -> int:
    """给新规则分配优先级：排在所有已有用户规则之前。

    后添加的规则通常是对前面的修正（比如发现漏了一种写法），应当先命中。
    """
    priorities = [r["priority"] for r in rules if isinstance(r.get("priority"), int)]
    if not priorities:
        return DEFAULT_PRIORITY
    return min(priorities) - 1


def add_user_rule(
    field: str,
    pattern: str,
    scope: str = GLOBAL_SCOPE,
    description: str = "",
    samples: Optional[List[str]] = None,
    label: str = "",
    rules_path: str = USER_RULES_FILE,
) -> Tuple[bool, str]:
    """新增一条用户规则并立即落盘。返回 (是否成功, 失败原因)。"""
    field = str(field or "").strip()
    if not field:
        return False, "变量名不能为空"

    ok, error = validate_pattern(pattern)
    if not ok:
        return False, error

    pattern = str(pattern).strip()
    scope = str(scope or GLOBAL_SCOPE).strip() or GLOBAL_SCOPE

    rules = load_user_rules(rules_path)
    for existing in rules:
        if (existing["field"] == field
                and existing["pattern"] == pattern
                and existing["scope"] == scope):
            return False, "这条规则已经存在，无需重复添加"

    clean_samples = [str(s).strip() for s in (samples or []) if str(s).strip()][:MAX_SAMPLES]
    rules.append({
        "field": field,
        "pattern": pattern,
        "priority": next_priority(rules),
        "label": str(label or field),
        "description": str(description or ""),
        "scope": scope,
        "source": USER_SOURCE,
        "samples": clean_samples,
        "created_at": _today(),
    })

    if not save_user_rules(rules, rules_path):
        return False, _last_error or "保存失败"
    return True, ""


def remove_user_rule(index: int, rules_path: str = USER_RULES_FILE) -> Tuple[bool, str]:
    """按下标删除一条用户规则。返回 (是否成功, 失败原因)。"""
    rules = load_user_rules(rules_path)
    if not 0 <= index < len(rules):
        return False, "规则不存在，可能已被其他操作改动，请刷新后重试"
    rules.pop(index)
    if not save_user_rules(rules, rules_path):
        return False, _last_error or "保存失败"
    return True, ""


def find_conflicts(
    pattern: str,
    other_rules: List[Dict[str, Any]],
    samples: Optional[List[str]] = None,
) -> List[str]:
    """检查新正则会和哪些已有规则抢同一个值，返回可直接展示的提示列表。

    两类冲突都要报：
      1. 新正则命中了本该属于别的字段的样本值（写太宽）
      2. 别的规则会先命中新规则的样本值（被抢走）——这类最隐蔽，
         因为用户写的正则完全正确却永远不生效。
    """
    messages: List[str] = []
    ok, error = validate_pattern(pattern)
    if not ok:
        return [f"正则语法有误，无法检查冲突：{error}"]

    try:
        compiled = compile_like_parser(pattern)
    except re.error:
        return messages

    for rule in other_rules:
        other_pattern = str(rule.get("pattern", "")).strip()
        if not other_pattern or other_pattern == str(pattern).strip():
            continue
        try:
            other_compiled = compile_like_parser(other_pattern)
        except re.error:
            continue

        other_name = _rule_display_name(rule)
        for sample in (samples or []):
            sample = str(sample).strip()
            if not sample:
                continue
            if compiled.match(sample) and other_compiled.match(sample):
                messages.append(
                    f"样本「{sample}」同时命中「{other_name}」({other_pattern})，"
                    f"两者会互相抢值"
                )
    return messages


def _rule_display_name(rule: Dict[str, Any]) -> str:
    """生成规则的可读名称，标注是内置还是用户自定义。"""
    field = str(rule.get("field", ""))
    if str(rule.get("source")) == USER_SOURCE:
        return f"{field}（用户规则）"
    return f"{field}（内置）"


def _today() -> str:
    """返回当天日期，用于记录规则创建时间。"""
    import datetime
    return datetime.date.today().isoformat()

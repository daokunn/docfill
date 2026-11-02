"""
变量管理模块
职责：
  1. 存储变量（名称、值、是否必填、来源）
  2. 加载 defaults.json 中的默认值（支持表达式）
  3. 必填/可选校验
  4. 自定义变量增删
  5. 对外提供"已解析值"字典（供文档填充使用）
不关心 UI、不处理文档。
"""

import csv
import io
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Set

from core.expression import evaluate, ExpressionError, try_evaluate
from core.date_format import format_output_values

from app_paths import config_path

# defaults.json 路径：优先读取 exe 同目录外置文件，否则使用 exe 内置资源
DEFAULTS_FILE = config_path("defaults.json")

# 复制粘贴常带的不可见字符：零宽空格/连接符、BOM、不换行空格、软连字符等。
# 注意不删普通空格和制表符（那些是用户可见的排版内容，由 strip 处理）。
_INVISIBLE_RE = re.compile(
    "[\u200b\u200c\u200d\u2060\ufeff\u00a0\u00ad\u202f\u205f\u3000]"
)


def clean_invisible(value: Any, enabled: bool = True) -> Any:
    """去除字符串中的不可见字符并裁剪首尾空白；非字符串原样返回。

    :param enabled: False 时只做首尾裁剪，不删不可见字符（设置里可关闭）
    """
    if not isinstance(value, str):
        return value
    text = _INVISIBLE_RE.sub("", value) if enabled else value
    return text.strip()


def round_half_up(value: Any, decimals: int = 0) -> Any:
    """数值四舍五入到指定小数位；非数值原样返回。

    decimals > 0 时返回固定小数位的字符串（例如 2 位时 300.7 → "300.70"），
    这样界面试算和写进模板都不会因为 float 显示而丢掉末尾的 0。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    try:
        places = max(0, min(6, int(decimals)))
        quantum = Decimal(1).scaleb(-places)
        rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
        if places == 0:
            return int(rounded)
        return f"{rounded:.{places}f}"
    except Exception:
        return value


class Variable:
    """单个变量"""

    def __init__(self, name: str, value: Any = "", required: bool = True,
                 source: str = "template", default_expr: str = ""):
        """单个变量"""
        self.name = name
        self.value = value              # 用户输入值（字符串）
        self.required = required        # 是否必填
        self.source = source            # template / custom / aux
        self.default_expr = default_expr  # 兼容旧 defaults.json 的默认表达式
        self.error: Optional[str] = None  # 校验错误信息
        # 用户规则（变量默认值与计算）
        self.rule_mode = "manual"       # manual / default / formula
        self.rule_expr = ""             # 默认值或公式
        self.rule_decimals = 0          # 小数位，默认 0（整数）
        self.apply_on_empty = True      # 名单空白时是否套用默认值
        self.export_summary = False     # 辅助变量是否写入汇总/移交清单
        self.kind = "template"          # template / aux
        self.allow_override = False     # 公式是否允许手动覆盖
        self.rule_error: Optional[str] = None

    def resolve(self, context: Dict[str, Any], apply_default: bool = True) -> Any:
        """计算变量的最终值。

        - formula：始终按公式计算（除非允许手动覆盖且用户填了值）
        - default：用户填了用用户值；没填才用默认值（apply_default 控制名单场景）
        - manual：保持原有行为（用户表达式/旧默认值）
        """
        self.rule_error = None

        if self.rule_mode == "formula":
            if self.allow_override and self.value not in (None, ""):
                try:
                    return round_half_up(evaluate(self.value, context), self.rule_decimals)
                except ExpressionError:
                    return self.value
            if not str(self.rule_expr or "").strip():
                return ""
            try:
                result = evaluate(self.rule_expr, context)
            except ExpressionError as exc:
                self.rule_error = str(exc)
                return ""
            return round_half_up(result, self.rule_decimals)

        if self.rule_mode == "default":
            if self.value not in (None, ""):
                return try_evaluate(self.value, context)
            if not apply_default:
                return ""
            expr = str(self.rule_expr or "").strip()
            if not expr:
                return ""
            try:
                result = evaluate(expr, context)
            except ExpressionError:
                # 默认值可以写普通文本，例如"某某公司"
                return expr
            return round_half_up(result, self.rule_decimals)

        # manual：兼容旧行为
        if self.value not in (None, ""):
            return try_evaluate(self.value, context)
        if self.default_expr:
            try:
                return evaluate(self.default_expr, context)
            except ExpressionError:
                return self.default_expr
        return ""

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "name": self.name,
            "value": self.value,
            "required": self.required,
            "source": self.source,
            "default_expr": self.default_expr,
            "rule_mode": self.rule_mode,
            "rule_expr": self.rule_expr,
            "rule_decimals": self.rule_decimals,
            "apply_on_empty": self.apply_on_empty,
            "export_summary": self.export_summary,
            "kind": self.kind,
            "allow_override": self.allow_override,
        }


class VariableManager:
    """变量管理器"""

    def __init__(self, business_name: str = "", strip_invisible: bool = True,
                 apply_defaults_on_empty: bool = True):
        """变量管理器"""
        self.business_name = business_name      # 所属业务名称
        self.strip_invisible = strip_invisible  # 是否去除粘贴带来的不可见字符
        self.apply_defaults_on_empty = apply_defaults_on_empty  # 名单批量默认值策略
        self.variables: Dict[str, Variable] = {}  # {变量名: Variable 对象}

    def init_from_template_vars(self, var_names: List[str], optional_vars: Optional[Set[str]] = None) -> None:
        """从模板扫描得到的变量名列表初始化。

        :param optional_vars: 模板中带 ``?`` 标记的可选变量名集合
        """
        optional = set(optional_vars or set())
        for name in var_names:
            name = (name or "").strip()
            if name and name not in self.variables:
                self.variables[name] = Variable(
                    name=name,
                    required=name not in optional,
                    source="template",
                )
        self._apply_defaults()
        self._apply_user_rules()

    def _apply_user_rules(self) -> None:
        """加载 config/user_variable_rules.json，覆盖默认值/公式并创建辅助变量。"""
        try:
            from core.variable_rules import merged_rules
            rules = merged_rules(self.business_name)
        except Exception:
            rules = {}
        if not rules:
            return
        for name, rule in rules.items():
            mode = str(rule.get("mode") or "manual")
            kind = str(rule.get("kind") or "template")
            var = self.variables.get(name)
            if var is None:
                if kind != "aux":
                    continue
                var = Variable(name=name, required=False, source="aux")
                var.kind = "aux"
                self.variables[name] = var
            var.rule_mode = mode if mode in ("manual", "default", "formula") else "manual"
            var.rule_expr = str(rule.get("expr") or "")
            var.rule_decimals = int(rule.get("decimals", 0) or 0)
            var.apply_on_empty = bool(rule.get("apply_on_empty", True))
            var.export_summary = bool(rule.get("export_summary", False))
            var.kind = kind if kind in ("template", "aux") else "template"
            var.allow_override = bool(rule.get("allow_override", False))
            if var.kind == "aux":
                var.required = False
                var.source = "aux"
            # 用户规则优先，旧 defaults.json 不再叠加
            var.default_expr = ""

    def _apply_defaults(self) -> None:
        """从 defaults.json 加载该业务的默认值表达式"""
        defaults = self._load_defaults()
        # 业务专属默认值
        biz_defaults = defaults.get(self.business_name, {})
        # 全局默认值（_全局默认）
        global_defaults = defaults.get("_全局默认", {})
        for name, var in self.variables.items():
            if name in biz_defaults:
                var.default_expr = str(biz_defaults[name])
            elif name in global_defaults:
                var.default_expr = str(global_defaults[name])

    @staticmethod
    def _load_defaults() -> Dict[str, Any]:
        """加载 defaults.json 默认值配置，文件不存在或损坏时返回空字典"""
        if not os.path.exists(DEFAULTS_FILE):
            return {}
        try:
            with open(DEFAULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def set_value(self, name: str, value: Any) -> None:
        """设置变量值，自动清除之前的错误标记；按设置去除不可见字符"""
        if name in self.variables:
            self.variables[name].value = clean_invisible(value, self.strip_invisible)
            self.variables[name].error = None

    def get_value(self, name: str) -> Any:
        """获取变量原始值（未解析表达式），不存在返回空字符串"""
        if name in self.variables:
            return self.variables[name].value
        return ""

    def get_resolved_value(self, name: str) -> Any:
        """获取单个变量的解析值（会先计算完整上下文）"""
        resolved = self.get_all_resolved()
        return resolved.get(name, "")

    def add_custom_variable(self, name: str, value: Any = "") -> None:
        """新增自定义变量"""
        if not name:
            return
        if name not in self.variables:
            self.variables[name] = Variable(
                name=name,
                value=clean_invisible(value, self.strip_invisible),
                required=False,
                source="custom",
            )

    def remove_variable(self, name: str) -> None:
        """删除变量（仅自定义变量可删，模板变量不可删）"""
        if name in self.variables and self.variables[name].source == "custom":
            del self.variables[name]

    def clear_values(self) -> None:
        """清空所有变量的值，保留变量结构、必填标记和默认值表达式。"""
        for var in self.variables.values():
            var.value = ""
            var.error = None

    def get_all_resolved(self) -> Dict[str, Any]:
        """
        返回所有变量的解析值字典，供文档填充使用。
        采用迭代解析策略，支持表达式链式依赖（A 依赖 B，B 依赖 C）。
        """
        # 初始上下文：所有变量的原始值
        ctx: Dict[str, Any] = {name: var.value for name, var in self.variables.items()}
        result: Dict[str, Any] = dict(ctx)

        # 迭代解析，最多 20 轮（处理链式依赖）
        for _ in range(20):
            changed = False
            for name, var in self.variables.items():
                apply_default = self.apply_defaults_on_empty or var.apply_on_empty
                try:
                    new_val = var.resolve(ctx, apply_default=apply_default)
                except Exception:
                    new_val = var.value
                if result.get(name) != new_val:
                    result[name] = new_val
                    changed = True
            ctx = dict(result)
            if not changed:
                break

        return result

    def get_output_values(self) -> Dict[str, Any]:
        """返回用于写入文档的值：先解析表达式，再按设置格式化日期。

        日期格式只影响输出文档，不影响表达式计算和界面上显示的原始值。
        """
        return format_output_values(self.get_all_resolved())

    def rule_errors(self) -> List[tuple]:
        """返回公式/默认值计算失败的变量及原因。"""
        return [(name, var.rule_error) for name, var in self.variables.items()
                if var.rule_error]

    def validate(self) -> List[str]:
        """
        校验必填变量。
        :return: 缺失的必填变量名列表
        """
        missing = []
        for name, var in self.variables.items():
            if var.kind == "aux" or var.rule_mode == "formula":
                continue
            has_default = bool(var.default_expr or (var.rule_mode == "default" and var.rule_expr))
            if var.required and var.value in (None, "") and not has_default:
                missing.append(name)
        return missing

    def get_optional_empty(self) -> List[str]:
        """返回值为空的可选变量（用于提示用户确认）"""
        empty = []
        for name, var in self.variables.items():
            if var.kind == "aux" or var.rule_mode == "formula":
                continue
            has_default = bool(var.default_expr or (var.rule_mode == "default" and var.rule_expr))
            if not var.required and var.value in (None, "") and not has_default:
                empty.append(name)
        return empty

    def to_list(self) -> List[dict]:
        """导出为列表（便于 UI 表格展示）"""
        return [v.to_dict() for v in self.variables.values()]

    def load_from_csv(self, csv_text: str) -> int:
        """
        从 CSV 文本批量导入变量值。
        CSV 格式：变量名,值
        :return: 成功导入的数量
        """
        count = 0
        reader = csv.reader(io.StringIO(csv_text))
        for row in reader:
            if len(row) >= 2 and row[0].strip():
                name = row[0].strip()
                value = row[1].strip()
                if name in self.variables:
                    self.set_value(name, value)
                    count += 1
                else:
                    # CSV 中有但模板里没有的，作为自定义变量
                    self.add_custom_variable(name, value)
                    count += 1
        return count

    def export_to_csv(self) -> str:
        """导出变量为 CSV 文本"""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["变量名", "值", "是否必填", "来源", "默认值表达式"])
        for v in self.variables.values():
            writer.writerow([v.name, v.value, "是" if v.required else "否", v.source, v.default_expr])
        return output.getvalue()

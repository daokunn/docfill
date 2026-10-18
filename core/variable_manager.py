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
from typing import Any, Dict, List, Optional, Set

from core.expression import evaluate, ExpressionError, try_evaluate
from core.date_format import format_output_values

from app_paths import config_path

# defaults.json 路径：优先读取 exe 同目录外置文件，否则使用 exe 内置资源
DEFAULTS_FILE = config_path("defaults.json")


class Variable:
    """单个变量"""

    def __init__(self, name: str, value: Any = "", required: bool = True,
                 source: str = "template", default_expr: str = ""):
        """单个变量"""
        self.name = name
        self.value = value              # 用户输入值（字符串）
        self.required = required        # 是否必填
        self.source = source            # template / custom
        self.default_expr = default_expr  # 默认值表达式（来自 defaults.json）
        self.error: Optional[str] = None  # 校验错误信息

    def resolve(self, context: Dict[str, Any]) -> Any:
        """
        计算变量的最终值（使用已解析的上下文，避免递归）。
        - 如果用户有输入，直接用用户值（若是表达式则求值）
        - 否则用默认值表达式求值
        """
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
        }


class VariableManager:
    """变量管理器"""

    def __init__(self, business_name: str = ""):
        """变量管理器"""
        self.business_name = business_name      # 所属业务名称
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
        """设置变量值，自动清除之前的错误标记"""
        if name in self.variables:
            self.variables[name].value = value
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
            self.variables[name] = Variable(name=name, value=value, required=False, source="custom")

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

        # 迭代解析，最多 10 轮（处理链式依赖）
        for _ in range(10):
            changed = False
            for name, var in self.variables.items():
                try:
                    new_val = var.resolve(ctx)
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

    def validate(self) -> List[str]:
        """
        校验必填变量。
        :return: 缺失的必填变量名列表
        """
        missing = []
        for name, var in self.variables.items():
            if var.required and var.value in (None, "") and not var.default_expr:
                missing.append(name)
        return missing

    def get_optional_empty(self) -> List[str]:
        """返回值为空的可选变量（用于提示用户确认）"""
        empty = []
        for name, var in self.variables.items():
            if not var.required and var.value in (None, "") and not var.default_expr:
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

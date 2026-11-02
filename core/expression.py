"""
变量表达式引擎
离线执行，基于 Python ast 白名单解析，禁用 eval/exec，保证安全。

支持能力：
  - 变量引用：直接写变量名，如 身份证号、姓名
  - 字符串字面量："文本" 或 '文本'
  - 数值运算：+ - * /
  - 字符串运算：+ 拼接
  - 内置函数：
      substr(字符串, 起始, 长度)     截取子串（身份证取出生日期：substr(身份证号,6,8)）
      concat(a, b, ...)              拼接多个值
      split(字符串, 分隔符, 索引)     按分隔符拆分后取第 N 段
      replace(字符串, 旧, 新)         替换
      upper(字符串) / lower(字符串)    大小写
      trim(字符串)                    去首尾空白
      len(字符串)                     长度
      today()                         当前日期 YYYY-MM-DD
      year() / month() / day()        当前年/月/日
      int(值) / str(值)               类型转换

用法：
  expr = "substr(身份证号, 6, 8)"
  result = evaluate(expr, {"身份证号": "360700199001011234"})
  # result = "19900101"
"""

import ast
import datetime
from typing import Any, Dict, Optional


class ExpressionError(Exception):
    """表达式语法或运行时错误"""
    pass


# 允许的 AST 节点类型白名单
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Num,        # py<3.8
    ast.Constant,   # py>=3.8
    ast.Str,        # py<3.8
    ast.Name,
    ast.Load,
    ast.Call,
    ast.Subscript,
    ast.Slice,
    ast.FunctionDef,
    ast.Return,
)


def _safe_functions() -> Dict[str, Any]:
    """返回允许在表达式中使用的函数字典"""
    import re as _re

    def substr(s: str, start: int, length: Optional[int] = None) -> str:
        """截取子串：substr(身份证号,6,8) 取身份证出生日期"""
        s = str(s)
        start = int(start)
        if length is None:
            return s[start:]
        return s[start:start + int(length)]

    def concat(*args) -> str:
        """拼接多个值为字符串"""
        return "".join(str(a) for a in args)

    def split(s: str, sep: str, index: int) -> str:
        """按分隔符拆分后取第 index 段（0 起始）"""
        parts = str(s).split(str(sep))
        idx = int(index)
        if 0 <= idx < len(parts):
            return parts[idx]
        return ""

    def replace(s: str, old: str, new: str) -> str:
        """字符串替换"""
        return str(s).replace(str(old), str(new))

    def upper(s: str) -> str:
        """转大写"""
        return str(s).upper()

    def lower(s: str) -> str:
        """转小写"""
        return str(s).lower()

    def trim(s: str) -> str:
        """去除首尾空白"""
        return str(s).strip()

    def length(s: str) -> int:
        """字符串长度"""
        return len(str(s))

    def today() -> str:
        """当前日期 YYYY-MM-DD"""
        return datetime.date.today().strftime("%Y-%m-%d")

    def year() -> str:
        """当前年份"""
        return str(datetime.date.today().year)

    def month() -> str:
        """当前月份"""
        return str(datetime.date.today().month)

    def day() -> str:
        """当前日"""
        return str(datetime.date.today().day)

    def to_int(v: Any) -> int:
        """转为整数"""
        return int(v)

    def to_str(v: Any) -> str:
        """转为字符串"""
        return str(v)

    def regex_extract(s: str, pattern: str, group: int = 0) -> str:
        """正则提取：regex_extract(文本, 模式, 分组序号)"""
        m = _re.search(pattern, str(s))
        if m:
            try:
                return m.group(group)
            except IndexError:
                return m.group(0)
        return ""

    return {
        "substr": substr,
        "concat": concat,
        "split": split,
        "replace": replace,
        "upper": upper,
        "lower": lower,
        "trim": trim,
        "len": length,
        "today": today,
        "year": year,
        "month": month,
        "day": day,
        "int": to_int,
        "str": to_str,
        "float": float,
        "round": round,
        "abs": abs,
        "min": min,
        "max": max,
        "regex_extract": regex_extract,
    }


_SAFE_FUNCTIONS = _safe_functions()


def _number(value: Any) -> Any:
    """把数字字符串转成数值；非数字原样返回。"""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return value
    return value


def _blank(value: Any) -> bool:
    """空值：None 或去掉空白后为空字符串。数字 0 不算空。"""
    return value is None or (isinstance(value, str) and not value.strip())


def _binop(op: str, left: Any, right: Any) -> Any:
    """数值字符串也按数字运算；空的可选变量在加减乘里自动忽略。"""
    a = _number(left)
    b = _number(right)
    if op == "+":
        # 可选变量为空时直接跳过，避免 A=B+C+D+E 因为 E 没填而报错
        if _blank(left) and _blank(right):
            return ""
        if _blank(left):
            return right
        if _blank(right):
            return left
        # 两个都是数字才做加法；只要有一边不是数字，就按文本拼接
        if isinstance(left, str) and isinstance(right, str):
            if isinstance(a, str) or isinstance(b, str):
                return left + right
            return a + b
        if isinstance(a, str) or isinstance(b, str):
            return f"{left}{right}"
        return a + b
    if op == "-":
        if _blank(right):
            return left if not _blank(left) else ""
        if _blank(left):
            return 0 - b
        return a - b
    if op == "*":
        if _blank(left) and _blank(right):
            return ""
        if _blank(left):
            return right
        if _blank(right):
            return left
        return a * b
    if _blank(left) or _blank(right):
        # 除法/取余/乘方缺少操作数时不做“猜一个 0”的危险处理
        return ""
    if op == "/":
        return a / b
    if op == "//":
        return a // b
    if op == "%":
        return a % b
    if op == "**":
        return a ** b
    raise ExpressionError(f"不支持的运算符：{op}")


def _unary(op: str, value: Any) -> Any:
    if _blank(value):
        return ""
    number = _number(value)
    if op == "-":
        return -number
    return +number


class _NumericOpTransformer(ast.NodeTransformer):
    """把 + - * / // % ** 换成带数值字符串兼容的 helper。"""

    _OPS = {
        ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
        ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
    }

    def visit_BinOp(self, node):  # noqa: N802
        self.generic_visit(node)
        op = self._OPS.get(type(node.op))
        if op is None:
            return node
        return ast.Call(
            func=ast.Name(id="_binop", ctx=ast.Load()),
            args=[ast.Constant(value=op), node.left, node.right],
            keywords=[],
        )

    def visit_UnaryOp(self, node):  # noqa: N802
        self.generic_visit(node)
        op = "-" if isinstance(node.op, ast.USub) else "+"
        return ast.Call(
            func=ast.Name(id="_unary", ctx=ast.Load()),
            args=[ast.Constant(value=op), node.operand],
            keywords=[],
        )


def _validate_node(node: ast.AST) -> None:
    """递归校验 AST 节点是否在白名单内"""
    if not isinstance(node, _ALLOWED_NODES):
        raise ExpressionError(f"表达式包含不支持的语法：{type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _validate_node(child)


def evaluate(expression: str, variables: Optional[Dict[str, Any]] = None) -> Any:
    """
    求值表达式。
    :param expression: 表达式字符串
    :param variables: 变量上下文字典 {变量名: 值}
    :return: 求值结果
    :raises ExpressionError: 语法错误或运行时错误
    """
    if not isinstance(expression, str) or not expression.strip():
        return ""

    variables = variables or {}
    expr = expression.strip()

    # 尝试解析为表达式
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"表达式语法错误：{e}")

    # 安全校验
    _validate_node(tree)
    tree = _NumericOpTransformer().visit(tree)
    ast.fix_missing_locations(tree)

    # 构建求值命名空间：变量 + 安全函数
    namespace: Dict[str, Any] = dict(_SAFE_FUNCTIONS)
    namespace.update({"_binop": _binop, "_unary": _unary})
    namespace.update(variables)

    try:
        result = eval(compile(tree, "<expression>", "eval"), {"__builtins__": {}}, namespace)
    except NameError as e:
        raise ExpressionError(f"表达式引用了未定义的变量或函数：{e}")
    except Exception as e:
        raise ExpressionError(f"表达式运行错误：{e}")

    return result


def is_expression(value: Any) -> bool:
    """
    判断一个值是否为表达式（需要求值）。
    简单规则：字符串中包含函数调用括号 或 引用了变量
    为避免误判，采用启发式：包含 ( 且不是纯文本的视为表达式
    """
    if not isinstance(value, str):
        return False
    # 包含函数调用特征：字母后跟 (
    if "(" in value and ")" in value:
        # 进一步检查是否有函数名模式
        import re
        if re.search(r"[A-Za-z_\u4e00-\u9fa5]+\s*\(", value):
            return True
    # 包含运算符且引用了变量（不在引号内），这里简化处理
    return False


def try_evaluate(value: Any, variables: Optional[Dict[str, Any]] = None) -> Any:
    """
    尝试对值进行表达式求值；如果不是表达式或求值失败，返回原值。
    """
    if is_expression(value):
        try:
            return evaluate(value, variables)
        except ExpressionError:
            return value
    return value

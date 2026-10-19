"""
DocFill 1.0.2 - 程序入口
支持 GUI（PySide6）和命令行（CLI）双模式。

用法：
  python main.py                          # 默认启动 GUI 界面
  python main.py --cli                    # 命令行交互式运行
  python main.py --set-template <目录>     # 设置模板根目录
  python main.py --set-output <目录>       # 设置输出根目录
  python main.py --list                   # 列出所有业务

核心流程：扫描模板目录 -> 提取{{变量}} -> 录入变量(手动/智能粘贴) -> 填充模板 -> 输出文档
"""

import argparse
import os
import sys
import traceback

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_paths import APP_DIR, APP_NAME, APP_VERSION, is_frozen, is_subpath, asset_path

if is_frozen():
    # windowed 模式打包后无控制台，stdout/stderr 为 None，print 会报错，统一兜底
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    def _write_crash_log(exc_type, exc_value, exc_tb) -> None:
        """GUI 未捕获异常时写入 error.log，便于排查闪退问题"""
        try:
            log_path = os.path.join(APP_DIR, "error.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        except IOError:
            pass

    sys.excepthook = _write_crash_log

from config.settings import get_settings
from core.scanner import scan_businesses, get_business_by_name, ordered_variable_names
from core.variable_manager import VariableManager
from core.renderer import render_document, RenderError
from core.parser import SmartParser
from core.field_mapper import map_fields_to_template
from core.preflight import collect_empty_variables, format_empty_summary
from output.file_output import OutputManager, OutputError


def set_template_dir(path: str) -> None:
    """设置模板根目录（命令行 --set-template）"""
    settings = get_settings()
    if not os.path.isdir(path):
        print(f"[错误] 目录不存在：{path}")
        return
    settings.template_root_dir = os.path.abspath(path)
    print(f"[已设置] 模板根目录：{settings.template_root_dir}")


def set_output_dir(path: str) -> None:
    """设置输出根目录（命令行 --set-output），目录不存在则创建"""
    settings = get_settings()
    template_root = settings.template_root_dir
    if template_root and is_subpath(path, template_root):
        print(f"[错误] 输出目录不能放在模板目录内：{path}")
        print("       请选择模板目录之外的文件夹。")
        return
    os.makedirs(path, exist_ok=True)
    settings.output_root_dir = os.path.abspath(path)
    print(f"[已设置] 输出根目录：{settings.output_root_dir}")


def list_businesses() -> None:
    """列出模板根目录下所有业务（命令行 --list）"""
    settings = get_settings()
    root = settings.template_root_dir
    if not root:
        print("[提示] 尚未设置模板根目录，请先运行：python main.py --set-template <目录>")
        return
    if not os.path.isdir(root):
        print(f"[错误] 模板根目录不存在：{root}")
        return
    businesses = scan_businesses(root)
    if not businesses:
        print(f"[提示] 模板根目录下没有业务文件夹：{root}")
        return
    print(f"扫描到 {len(businesses)} 项业务：")
    for i, b in enumerate(businesses, 1):
        var_count = len(b.variables)
        tmpl_count = len(b.templates)
        print(f"  [{i}] {b.name}  （模板 {tmpl_count} 个，变量 {var_count} 个）")


def select_business_interactive():
    """交互式选择业务"""
    settings = get_settings()
    root = settings.template_root_dir
    if not root or not os.path.isdir(root):
        print("[提示] 请先设置模板根目录：python main.py --set-template <目录>")
        return None

    businesses = scan_businesses(root)
    if not businesses:
        print("[提示] 没有可用的业务")
        return None

    print("\n请选择要处理的业务：")
    for i, b in enumerate(businesses, 1):
        print(f"  [{i}] {b.name}")

    while True:
        try:
            choice = input("输入序号：").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(businesses):
                return businesses[idx]
            print("序号超出范围，请重新输入")
        except (ValueError, EOFError):
            print("请输入有效数字")


def smart_paste(vm: VariableManager) -> None:
    """智能粘贴解析：用户粘贴文本，自动识别并回填变量"""
    print("\n=== 智能粘贴解析 ===")
    print("请粘贴原始业务文本（输入空行结束）：")
    lines = []
    try:
        while True:
            line = input()
            if line.strip() == "":
                break
            lines.append(line)
    except EOFError:
        pass

    text = "\n".join(lines)
    if not text.strip():
        print("[提示] 未输入任何内容")
        return

    parser = SmartParser(business_name=vm.business_name)
    result = parser.parse(text)
    fields = map_fields_to_template(result.fields, list(vm.variables))

    print(f"\n识别到 {result.field_count} 个字段：")
    print("-" * 50)
    for f in fields:
        conflict_mark = " [冲突]" if f.conflict else ""
        match_mark = f" [自动匹配自 {f.mapped_from}]" if f.mapped_from else ""
        unused_mark = " [模板中无]" if not f.in_template else ""
        print(f"  {f.label}({f.field}) = {f.value}{conflict_mark}{match_mark}{unused_mark}")
        if f.alternatives:
            print(f"    候选值: {f.alternatives}")

    if result.conflicts:
        print(f"\n[注意] 以下字段存在冲突：{', '.join(result.conflicts)}")
        print("当前取第一个值，如需修改请在后续手动调整。")

    if result.unrecognized:
        print(f"\n[未识别] {len(result.unrecognized)} 个片段：")
        for u in result.unrecognized:
            print(f"    {u}")

    # 回填到变量管理器：只写入模板中存在的变量
    filled = 0
    skipped = 0
    for f in fields:
        if not f.in_template:
            skipped += 1
            continue
        vm.set_value(f.field, f.value)
        filled += 1

    print(f"\n已回填 {filled} 个变量到变量表。")
    if skipped:
        print(f"[提示] {skipped} 个识别字段在当前模板中没有对应变量，已跳过。")


def input_variables(vm: VariableManager) -> bool:
    """交互式录入变量值（支持智能粘贴 + 手动调整）"""
    # 先询问是否使用智能粘贴
    try:
        use_smart = input("\n是否使用智能粘贴解析？(y/n): ").strip().lower()
    except EOFError:
        use_smart = "n"

    if use_smart == "y":
        smart_paste(vm)

    # 手动调整/补充
    print(f"\n当前变量（共 {len(vm.variables)} 个），可逐项修改（直接回车保留当前值）：")
    print("-" * 50)
    for name, var in vm.variables.items():
        required_mark = "*必填*" if var.required else " 可选 "
        current = var.value if var.value else ""
        default_hint = f" [默认: {var.default_expr}]" if var.default_expr and not var.value else ""
        display = current if current else default_hint
        prompt = f"  {required_mark} {name}{display}: "
        try:
            value = input(prompt).strip()
        except EOFError:
            value = ""
        if value:
            vm.set_value(name, value)

    # 校验必填
    missing = vm.validate()
    if missing:
        print(f"\n[警告] 以下必填变量未填写：{', '.join(missing)}")
        print("请补充填写后重新生成。")
        return False

    # 提示可选为空
    optional_empty = vm.get_optional_empty()
    if optional_empty:
        print(f"\n[提示] 以下可选变量为空：{', '.join(optional_empty)}")
        try:
            confirm = input("是否继续生成？(y/n): ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y":
            return False
    return True


def generate_documents(business, vm: VariableManager) -> bool:
    """生成所有文档"""
    settings = get_settings()
    output_mgr = OutputManager()

    # 检查输出目录
    if not settings.output_root_dir:
        print("[提示] 尚未设置输出根目录")
        try:
            out_dir = input("请输入输出根目录路径：").strip()
        except EOFError:
            out_dir = ""
        if not out_dir:
            print("[错误] 未设置输出目录，终止生成")
            return False
        set_output_dir(out_dir)

    resolved = vm.get_output_values()

    missing = collect_empty_variables(business, resolved)
    if missing:
        print(f"\n[提示] {format_empty_summary(business.name, missing)}")
        try:
            confirm = input("仍然生成吗？未填位置会留空 (y/n): ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y":
            print("已取消生成，请补充变量后重试。")
            return False

    try:
        output_dir = output_mgr.get_output_dir(business.name, resolved)
    except OutputError as e:
        print(f"[错误] {e}")
        return False

    logger = output_mgr.get_logger(output_dir)
    logger.info(f"===== 开始生成业务：{business.name} =====")
    logger.info(f"输出目录：{output_dir}")

    print(f"\n输出目录：{output_dir}")
    success_count = 0
    fail_count = 0

    for tmpl in business.templates:
        if tmpl.error:
            print(f"  [跳过] {tmpl.name}：{tmpl.error}")
            logger.warning(f"跳过模板 {tmpl.name}：{tmpl.error}")
            fail_count += 1
            continue

        output_path = output_mgr.resolve_output_path(tmpl.rel_path, output_dir, resolved)
        if not output_path:
            print(f"  [跳过] {tmpl.name}：文件已存在（跳过策略）")
            logger.info(f"跳过（已存在）：{tmpl.name}")
            continue

        try:
            layout_log = []
            render_document(
                tmpl.path,
                output_path,
                resolved,
                shrink_overflow_font=bool(settings.get("shrink_overflow_font", True)),
                layout_log=layout_log,
            )
            print(f"  [成功] {tmpl.name} -> {os.path.basename(output_path)}")
            for msg in layout_log:
                print(f"    [版式] {msg}")
                logger.info(f"版式调整：{msg}")
            logger.info(f"生成成功：{tmpl.name} -> {output_path}")
            success_count += 1
        except RenderError as e:
            print(f"  [失败] {tmpl.name}：{e}")
            logger.error(f"生成失败 {tmpl.name}：{e}")
            fail_count += 1

    logger.info(f"===== 生成完成：成功 {success_count}，失败 {fail_count} =====")
    print(f"\n生成完成：成功 {success_count} 个，失败 {fail_count} 个")
    print(f"日志文件：{os.path.join(output_dir, settings.get('log_filename', 'operation.log'))}")
    output_mgr.reset_logger()
    return True


def interactive_run() -> None:
    """交互式主流程"""
    print("=" * 50)
    print("  DocFill · 文档智能解析与批量填充")
    print("=" * 50)

    settings = get_settings()
    print(f"模板根目录：{settings.template_root_dir or '(未设置)'}")
    print(f"输出根目录：{settings.output_root_dir or '(未设置)'}")

    business = select_business_interactive()
    if not business:
        return

    print(f"\n已选择业务：{business.name}")
    print(f"模板文件：{len(business.templates)} 个")
    print(f"变量数量：{len(business.variables)} 个")

    # 初始化变量管理器
    vm = VariableManager(
        business_name=business.name,
        strip_invisible=bool(settings.get("strip_invisible_chars", True)),
    )
    vm.init_from_template_vars(
        ordered_variable_names(business, settings.get("variable_order", "template")),
        business.optional_variables,
    )

    # 录入变量
    if not input_variables(vm):
        return

    # 生成文档
    generate_documents(business, vm)


def run_gui() -> None:
    """启动 PySide6 GUI 界面"""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon
    except ImportError:
        print("[错误] 未安装 PySide6，无法启动 GUI。请运行：pip install PySide6")
        print("或使用命令行模式：python main.py --cli")
        return

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("DocFill")
    icon_file = asset_path("docfill.ico")
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))
    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    # onefile 启动图：主窗口出现后关闭，避免启动图一直停留在桌面
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass
    sys.exit(app.exec())


def main():
    """程序入口：解析命令行参数，默认启动 GUI，--cli 进入命令行模式"""
    parser = argparse.ArgumentParser(description="DocFill - 文档智能解析与批量填充工具")
    parser.add_argument("--cli", action="store_true", help="使用命令行交互模式（默认启动 GUI）")
    parser.add_argument("--set-template", metavar="DIR", help="设置模板根目录")
    parser.add_argument("--set-output", metavar="DIR", help="设置输出根目录")
    parser.add_argument("--list", action="store_true", help="列出所有业务")
    args = parser.parse_args()

    if args.set_template:
        set_template_dir(args.set_template)
        return
    if args.set_output:
        set_output_dir(args.set_output)
        return
    if args.list:
        list_businesses()
        return

    if args.cli:
        interactive_run()
    else:
        run_gui()


if __name__ == "__main__":
    main()

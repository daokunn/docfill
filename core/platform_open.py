"""跨平台系统交互封装。

存在的唯一理由：让业务代码不必关心操作系统差异。
全项目只有"打开文件夹"这类动作需要区分平台，其余代码在 Windows 和
银河麒麟（Linux/arm64）上完全共用。

为什么要单独抽出来：
  os.startfile() 是 Windows 独有的，在 Linux 上调用会抛 AttributeError。
  而 AttributeError 不是 OSError 的子类，所以外面套的
  `try: os.startfile(...) except OSError:` 根本接不住，程序会直接崩溃。
  这是从 Windows 移植到麒麟时最容易踩、且崩得最莫名其妙的一处。
"""

import os
import platform
import subprocess
import sys
from typing import List, Optional

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Linux 桌面环境下可能存在的文件管理器/打开命令，按优先级尝试。
# 银河麒麟 UKUI 桌面自带 peony，Ubuntu/GNOME 是 nautilus，KDE 是 dolphin。
_LINUX_OPENERS: List[List[str]] = [
    ["xdg-open"],     #  freedesktop 标准，多数麒麟版本已预装
    ["peony"],        #  银河麒麟 UKUI 桌面自带文件管理器
    ["caja"],         #  UKUI 早期版本 / MATE
    ["dolphin"],      #  KDE
    ["nautilus"],     #  GNOME
    ["thunar"],       #  XFCE
]


def platform_name() -> str:
    """返回当前平台的中文名称，用于日志和界面提示。"""
    if IS_WINDOWS:
        return "Windows"
    if IS_MACOS:
        return "macOS"
    if IS_LINUX:
        return "Linux"
    return platform.system() or "未知系统"


def machine_arch() -> str:
    """返回 CPU 架构，用于排查信创平台的依赖包不匹配问题。

    麒麟上常见 aarch64（飞腾/鲲鹏）、x86_64（兆芯/海光）、
    loongarch64（龙芯）。装错架构的 PySide6 会报
    "GLIBC_x.xx not found" 这类看不懂的错误，先把架构显示出来能省很多排查时间。
    """
    return platform.machine() or "unknown"


def environment_summary() -> str:
    """一行式环境摘要，写进日志方便远程排查。"""
    return (f"{platform_name()} {platform.release()} / "
            f"{machine_arch()} / Python {platform.python_version()}")


def _find_linux_opener() -> Optional[List[str]]:
    """找出当前系统上可用的"打开文件夹"命令。"""
    from shutil import which

    for opener in _LINUX_OPENERS:
        if which(opener[0]):
            return opener
    return None


def open_folder(path: str) -> bool:
    """用系统文件管理器打开目录。成功返回 True。

    安全要点：命令和路径分开作为参数列表传入，不使用 shell=True。
    输出目录名里含客户姓名、日期等可变内容（如「公务卡申请_张三_202610」），
    一旦拼进 shell 字符串，特殊字符就可能被解释执行。

    失败不抛异常，返回 False 由调用方决定怎么提示用户——
    打不开文件夹不该让整个程序崩掉。
    """
    if not path:
        return False

    folder = os.path.abspath(str(path))
    if not os.path.isdir(folder):
        return False

    try:
        if IS_WINDOWS:
            # 优先用资源管理器打开并选中该目录
            subprocess.Popen(["explorer", folder])
            return True

        if IS_MACOS:
            subprocess.Popen(["open", folder])
            return True

        opener = _find_linux_opener()
        if opener is None:
            return False
        # 与父进程解绑，避免文件管理器变成子进程被一起回收
        subprocess.Popen(opener + [folder],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def open_file(path: str) -> bool:
    """用系统默认程序打开单个文件；失败返回 False。"""
    if not path:
        return False
    target = os.path.abspath(str(path))
    if not os.path.isfile(target):
        return False
    try:
        if IS_WINDOWS:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        if IS_MACOS:
            subprocess.Popen(["open", target])
            return True
        opener = _find_linux_opener()
        if opener is None:
            return False
        subprocess.Popen(opener + [target],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def open_folder_error_hint(path: str) -> str:
    """生成打开目录失败时的用户提示文案。"""
    folder = os.path.abspath(str(path or ""))
    if not os.path.isdir(folder):
        return f"目录不存在或已被移动：{folder}"

    if IS_LINUX:
        return (
            f"当前系统没有可用的文件管理器命令，无法自动打开目录。\n"
            f"请手动打开：{folder}\n\n"
            f"（可让管理员安装 xdg-utils，或直接在文件管理器地址栏粘贴上面的路径）"
        )
    return f"无法打开目录：{folder}"


def app_icon_file(prefer_png: bool = True) -> str:
    """返回适合当前平台的图标文件绝对路径，找不到返回空字符串。

    Linux 桌面对 .ico 支持参差，任务栏/菜单图标优先用 .png；
    Windows 沿用 .ico（exe 图标和窗口图标一致）。
    """
    try:
        from app_paths import asset_path
    except ImportError:
        return ""

    if IS_WINDOWS:
        candidates = ["docfill.ico", "docfill.png"]
    elif prefer_png:
        candidates = ["docfill.png", "docfill.ico"]
    else:
        candidates = ["docfill.ico", "docfill.png"]

    for name in candidates:
        try:
            path = asset_path(name)
        except Exception:
            continue
        if path and os.path.exists(path):
            return path
    return ""

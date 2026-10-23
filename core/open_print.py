"""生成后打开与打印。

设计取舍：
- 先按用户设置用系统默认程序打开文件（文件保持打开，程序不负责关闭）。
- 再调用系统打印动作：
    Windows: 资源管理器的 "print" 动词，通常使用默认打印机、不弹打印对话框
    macOS/Linux: lp / lpr，本身即静默
- 是否真正静默取决于系统默认打印机和文件关联程序；程序这边不再弹任何打印框。
- 打印失败不影响已生成的文件，只记录提示。
"""

import os
import subprocess
import sys
from typing import Iterable, List, Tuple

from core.platform_open import open_file

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def open_files(paths: Iterable[str]) -> Tuple[int, int]:
    """打开一批文件，返回 (成功数, 失败数)。"""
    opened = failed = 0
    for path in paths:
        if open_file(path):
            opened += 1
        else:
            failed += 1
    return opened, failed


def print_file(path: str, copies: int = 1, printer: str = "") -> bool:
    """把单个文件送到打印机；copies 份，printer 为空时用系统默认。"""
    target = os.path.abspath(str(path or ""))
    if not os.path.isfile(target):
        return False
    copies = max(1, int(copies or 1))
    printer = str(printer or "").strip()
    try:
        if IS_WINDOWS:
            for _ in range(copies):
                if printer:
                    try:
                        os.startfile(target, "printto", f'"{printer}"')  # type: ignore[attr-defined]
                        continue
                    except (OSError, ValueError):
                        pass
                os.startfile(target, "print")  # type: ignore[attr-defined]
            return True
        if IS_MACOS:
            command = ["lp"]
            if printer:
                command += ["-d", printer]
            command += ["-n", str(copies), target]
            subprocess.Popen(command, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        if IS_LINUX:
            for base in ("lp", "lpr"):
                command = [base]
                if printer and base == "lp":
                    command += ["-d", printer]
                if base == "lp":
                    command += ["-n", str(copies)]
                else:
                    command += ["-#", str(copies)]
                command.append(target)
                try:
                    subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    return True
                except (OSError, ValueError):
                    continue
            return False
        return False
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def print_files(paths: Iterable[str], copies: int = 1,
                printer: str = "") -> Tuple[int, int]:
    """打印一批文件，返回 (成功数, 失败数)。"""
    printed = failed = 0
    for path in paths:
        if print_file(path, copies=copies, printer=printer):
            printed += 1
        else:
            failed += 1
    return printed, failed

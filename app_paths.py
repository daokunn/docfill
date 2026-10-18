"""
应用路径解析模块（PyInstaller 打包适配层）
职责：
  统一管理配置文件、数据文件在"开发环境"与"打包后 exe 环境"下的路径定位，
  对上层模块屏蔽 PyInstaller 的临时解压机制（sys._MEIPASS）。

路径策略：
  1. 只读资源（rules.json / defaults.json / region_dict.json）：
     打包时内置在 exe 中；若 exe 同目录存在同名外置文件，则外置优先（便于高级用户自定义）。
  2. 可写配置（settings.json / aliases.json）：
     固定存放在 exe 同目录的 config/ 下，重启不丢失；
     首次运行时自动把内置默认文件释放一份（仅 aliases.json 有内置初始数据）。

重要变量：
  APP_DIR    程序目录：打包后为 exe 所在目录（可写），开发时为项目根目录
  BUNDLE_DIR 资源目录：打包后为 PyInstaller 临时解压目录（只读内置资源），开发时同为项目根目录
"""

import os
import shutil
import sys


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的环境中"""
    return bool(getattr(sys, "frozen", False))


# 项目根目录（本文件位于项目根目录）
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

if is_frozen():
    # onefile 模式：sys.executable 是 exe 路径；sys._MEIPASS 是内置资源的临时解压目录
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = _PROJECT_ROOT
    BUNDLE_DIR = _PROJECT_ROOT


def _resolve(folder: str, name: str, writable: bool) -> str:
    """
    解析资源文件的实际路径。
    :param folder: 资源所在文件夹名（config / data）
    :param name: 文件名
    :param writable: 是否为需要持久化的可写文件
    :return: 可用的文件绝对路径
    """
    external_path = os.path.join(APP_DIR, folder, name)
    bundled_path = os.path.join(BUNDLE_DIR, folder, name)

    if writable:
        # 可写文件固定放 exe 同目录，确保目录存在；首次运行时释放内置默认文件
        os.makedirs(os.path.dirname(external_path), exist_ok=True)
        if not os.path.exists(external_path) and os.path.exists(bundled_path):
            shutil.copyfile(bundled_path, external_path)
        return external_path

    # 只读文件：外置优先（方便用户自定义），否则使用 exe 内置资源
    if os.path.exists(external_path):
        return external_path
    return bundled_path


def config_path(name: str, writable: bool = False) -> str:
    """获取 config 目录下文件的路径（settings.json/aliases.json 需 writable=True）"""
    return _resolve("config", name, writable)


def data_path(name: str, writable: bool = False) -> str:
    """获取 data 目录下文件的路径"""
    return _resolve("data", name, writable)


def asset_path(name: str) -> str:
    """获取 assets 目录下只读资源（图标/启动图）的路径。"""
    return _resolve("assets", name, writable=False)


def is_subpath(child: str, parent: str) -> bool:
    """判断 child 是否等于 parent 或位于 parent 目录内部（大小写不敏感）。"""
    if not child or not parent:
        return False
    child_path = os.path.normcase(os.path.abspath(child))
    parent_path = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath([child_path, parent_path]) == parent_path
    except ValueError:
        return False

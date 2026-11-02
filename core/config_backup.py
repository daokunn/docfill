"""配置备份与恢复。

备份内容（都在 exe 同目录）：
  config/settings.json      用户设置
  config/aliases.json       变量别名
  config/user_rules.json    自定义识别规则
  config/defaults.json      自定义默认值（如存在）
  config/rules.json         外置识别规则（如存在）
  .docfill_state/           名单、自动编号台账、上次数据

不备份：模板文件、输出文件、操作日志、error.log。

恢复前会自动把当前配置备份到 .docfill_backups/，恢复后重启或刷新界面生效。
"""

import datetime
import json
import os
import zipfile
from typing import List, Optional, Tuple

from app_paths import APP_VERSION

BACKUP_DIR_NAME = ".docfill_backups"
BACKUP_MANIFEST = "docfill_backup.json"
STATE_DIR_NAME = ".docfill_state"

CONFIG_FILES = (
    "config/settings.json",
    "config/aliases.json",
    "config/user_rules.json",
    "config/user_variable_rules.json",
    "config/defaults.json",
    "config/rules.json",
)
ALLOWED_PREFIXES = ("config/", STATE_DIR_NAME + "/")


class ConfigBackupError(Exception):
    """配置备份/恢复失败。"""


def collect_files(app_dir: str, include_history: bool = True) -> List[str]:
    """收集应备份的相对路径。"""
    files: List[str] = []
    for relative in CONFIG_FILES:
        if os.path.isfile(os.path.join(app_dir, relative)):
            files.append(relative)
    state_dir = os.path.join(app_dir, STATE_DIR_NAME)
    history_file = os.path.join(state_dir, "history.json")
    if os.path.isdir(state_dir):
        for root, _dirs, names in os.walk(state_dir):
            for name in names:
                if name.endswith(".tmp"):
                    continue
                absolute = os.path.join(root, name)
                if not include_history and os.path.normcase(absolute) == os.path.normcase(history_file):
                    continue
                relative = os.path.relpath(absolute, app_dir).replace(os.sep, "/")
                files.append(relative)
    return sorted(files)


def default_backup_name() -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return f"DocFill配置备份_{stamp}.zip"


def create_backup(app_dir: str, destination: str,
                  include_history: bool = True) -> Tuple[int, List[str]]:
    """把配置和名单状态打包成 zip，返回 (文件数, 文件列表)。"""
    if not destination:
        raise ConfigBackupError("没有指定备份文件路径。")
    files = collect_files(app_dir, include_history=include_history)
    if not files:
        raise ConfigBackupError("没有找到可备份的配置。")

    folder = os.path.dirname(os.path.abspath(destination))
    if folder:
        os.makedirs(folder, exist_ok=True)
    manifest = {
        "app": "DocFill",
        "version": APP_VERSION,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "include_history": bool(include_history),
        "files": files,
    }
    try:
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                BACKUP_MANIFEST,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            for relative in files:
                archive.write(os.path.join(app_dir, relative), relative)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ConfigBackupError(f"写入备份失败：{exc}") from exc
    return len(files), files


def _safe_members(archive: zipfile.ZipFile) -> List[str]:
    """只允许 config/ 和 .docfill_state/ 下的文件，拒绝路径穿越。"""
    members: List[str] = []
    for name in archive.namelist():
        if name == BACKUP_MANIFEST or name.endswith("/"):
            continue
        normalized = name.replace("\\", "/")
        if not any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        parts = normalized.split("/")
        if any(part in ("", ".", "..") for part in parts):
            continue
        members.append(normalized)
    return members


def restore_backup(app_dir: str, source: str,
                   auto_backup: bool = True) -> Tuple[int, Optional[str]]:
    """从 zip 恢复配置；返回 (恢复文件数, 自动备份路径)。"""
    if not source or not os.path.isfile(source):
        raise ConfigBackupError("备份文件不存在。")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            members = _safe_members(archive)
            if not members:
                raise ConfigBackupError("备份包里没有可恢复的配置。")
            if "config/settings.json" not in members:
                raise ConfigBackupError("备份包里缺少 config/settings.json。")

            backup_path = None
            if auto_backup:
                backup_dir = os.path.join(app_dir, BACKUP_DIR_NAME)
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = os.path.join(backup_dir, f"恢复前备份_{stamp}.zip")
                try:
                    create_backup(app_dir, backup_path)
                except ConfigBackupError:
                    backup_path = None

            # 先读入内存，确认完整后再写，避免恢复一半
            payload = {name: archive.read(name) for name in members}
    except zipfile.BadZipFile as exc:
        raise ConfigBackupError(f"不是有效的备份文件：{exc}") from exc
    except OSError as exc:
        raise ConfigBackupError(f"读取备份失败：{exc}") from exc

    for name, data in payload.items():
        target = os.path.join(app_dir, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    return len(payload), backup_path

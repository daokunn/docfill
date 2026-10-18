"""模板修改前的备份与撤销。

“统一变量名”会直接改写模板文件。每次修改前把受影响文件复制到
``.docfill_backups/<时间戳>/``，并记录 last_backup.json，支持一键恢复。
"""

import datetime
import hashlib
import json
import os
import shutil
from typing import Dict, Iterable, List, Optional

from app_paths import APP_DIR

BACKUP_DIR_NAME = ".docfill_backups"


def _default_root() -> str:
    return os.path.join(APP_DIR, BACKUP_DIR_NAME)


def _relative_name(path: str) -> str:
    """生成备份内的相对路径；项目外的文件用哈希避免重名。"""
    absolute = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute, APP_DIR)
    except ValueError:
        relative = ""
    if relative and not relative.startswith("..") and not os.path.isabs(relative):
        return relative
    digest = hashlib.sha1(absolute.encode("utf-8")).hexdigest()[:12]
    return os.path.join("_external", digest + "_" + os.path.basename(absolute))


def backup_templates(
    paths: Iterable[str],
    backup_root: Optional[str] = None,
    reason: str = "normalize",
) -> Dict:
    """备份一组模板文件，返回备份记录。

    备份失败会抛出异常，调用方应在修改模板前中止。
    """
    root = backup_root or _default_root()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = os.path.join(root, stamp)
    os.makedirs(backup_dir, exist_ok=True)

    files: List[Dict[str, str]] = []
    seen = set()
    for path in paths:
        absolute = os.path.abspath(str(path))
        if absolute in seen or not os.path.exists(absolute):
            continue
        seen.add(absolute)
        relative = _relative_name(absolute)
        target = os.path.join(backup_dir, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(absolute, target)
        files.append({
            "original": absolute,
            "backup": target,
            "relative": relative,
        })

    record = {
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
        "backup_dir": backup_dir,
        "files": files,
    }
    manifest_path = os.path.join(backup_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(root, "last_backup.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    return record


def get_last_backup(backup_root: Optional[str] = None) -> Optional[Dict]:
    """读取最近一次备份记录；不存在或损坏返回 None。"""
    root = backup_root or _default_root()
    path = os.path.join(root, "last_backup.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
        if not record.get("files"):
            return None
        return record
    except (json.JSONDecodeError, IOError):
        return None


def has_last_backup(backup_root: Optional[str] = None) -> bool:
    """是否存在可恢复的备份。"""
    return bool(get_last_backup(backup_root))


def restore_backup(
    record: Optional[Dict] = None,
    backup_root: Optional[str] = None,
) -> int:
    """把备份文件复制回原位置，返回恢复的文件数。"""
    record = record or get_last_backup(backup_root)
    if not record:
        return 0

    restored = 0
    for item in record.get("files", []):
        original = item.get("original", "")
        backup = item.get("backup", "")
        if not original or not backup or not os.path.exists(backup):
            continue
        os.makedirs(os.path.dirname(original), exist_ok=True)
        shutil.copy2(backup, original)
        restored += 1
    return restored


def restore_last_backup(backup_root: Optional[str] = None) -> int:
    """恢复最近一次统一变量名前的模板。"""
    return restore_backup(get_last_backup(backup_root), backup_root)


def clear_last_backup(backup_root: Optional[str] = None) -> None:
    """清除“最近一次备份”指针，保留备份目录本身。"""
    root = backup_root or _default_root()
    path = os.path.join(root, "last_backup.json")
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

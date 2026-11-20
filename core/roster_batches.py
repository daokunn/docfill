"""同一业务下的多批次名单。

设计约定：
  - 每业务一个索引 `.docfill_state/batches_<业务>/index.json`，记录批次列表和当前批次。
  - 每批次仍是一份标准的 roster JSON，沿用 core.roster.Roster 的全部读写逻辑。
  - 旧的单文件名单 `roster_<业务>.json` 首次访问时迁移成"默认批次"，
    原文件保留不动——迁移出错也不会丢用户数据。
  - 删除批次只删该批次文件和索引项，不做回收站（用户已确认）。
"""

import datetime
import json
import os
import uuid
from typing import Dict, List, Optional, Sequence

from app_paths import APP_DIR
from core.roster import (
    ROSTER_DIR_NAME, Roster, _sanitize_business_name, roster_path,
)

BATCH_DIR_PREFIX = "batches_"
INDEX_FILE = "index.json"
DEFAULT_BATCH_NAME = "默认批次"


def batch_dir(business_name: str, storage_dir: Optional[str] = None) -> str:
    folder = storage_dir or os.path.join(APP_DIR, ROSTER_DIR_NAME)
    return os.path.join(folder, f"{BATCH_DIR_PREFIX}{_sanitize_business_name(business_name)}")


def batch_index_path(business_name: str, storage_dir: Optional[str] = None) -> str:
    return os.path.join(batch_dir(business_name, storage_dir), INDEX_FILE)


def _atomic_json(path: str, payload: dict) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_index(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("batches"), list):
        return None
    return data


def _write_index(business_name: str, index: dict, storage_dir: Optional[str] = None) -> None:
    index["business"] = str(business_name or "")
    _atomic_json(batch_index_path(business_name, storage_dir), index)


def _new_batch_id() -> str:
    return "b_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _batch_file_path(business_name: str, filename: str,
                     storage_dir: Optional[str] = None) -> str:
    return os.path.join(batch_dir(business_name, storage_dir), filename)


def _create_empty_batch(business_name: str, name: str,
                        key_field: str = "姓名",
                        storage_dir: Optional[str] = None) -> Dict[str, str]:
    batch_id = _new_batch_id()
    filename = f"{batch_id}.json"
    roster = Roster(business_name, key_field=key_field,
                    storage_path=_batch_file_path(business_name, filename, storage_dir))
    roster.ensure_columns([key_field])
    roster.save()
    return {"id": batch_id, "name": name, "file": filename}


def _migrate_legacy(business_name: str, index_path: str,
                    storage_dir: Optional[str] = None) -> dict:
    """把旧的单文件名单搬进默认批次；旧文件原样保留。"""
    legacy = roster_path(business_name, storage_dir)
    key_field = "姓名"
    payload = None
    migration_error = ""
    if os.path.exists(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                payload = data
                key_field = str(data.get("key_field") or "姓名").strip() or "姓名"
            else:
                raise ValueError("顶层不是对象")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            # 名单损坏：先把坏文件改名留证，再建空批次；错误必须传到界面，
            # 不能让用户以为数据凭空消失后继续保存覆盖。
            backup = legacy + ".corrupt." + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            try:
                os.replace(legacy, backup)
                migration_error = (
                    f"原名单文件已损坏（{exc}），已备份到：{backup}。"
                    "当前显示为空名单，请检查备份文件后再决定是否继续录入。"
                )
            except OSError:
                migration_error = f"原名单文件已损坏（{exc}），且备份失败，请勿覆盖原文件。"

    batch = _create_empty_batch(business_name, DEFAULT_BATCH_NAME, key_field, storage_dir)
    if payload is not None:
        migrated = dict(payload)
        migrated["business"] = business_name
        migrated["key_field"] = key_field
        _atomic_json(_batch_file_path(business_name, batch["file"], storage_dir), migrated)

    index = {
        "version": 1,
        "business": business_name,
        "key_field": key_field,
        "active": batch["id"],
        "batches": [batch],
    }
    if migration_error:
        index["migration_error"] = migration_error
    _write_index(business_name, index, storage_dir)
    return index


def ensure_library(business_name: str, storage_dir: Optional[str] = None) -> dict:
    """确保批次索引存在；不存在则从旧名单迁移或新建默认批次。"""
    index_path = batch_index_path(business_name, storage_dir)
    index = _read_index(index_path)
    if index is not None:
        return index
    if os.path.exists(index_path):
        # 索引损坏：备份后重建，绝不直接覆盖用户的坏文件
        try:
            os.replace(index_path, index_path + ".corrupt." +
                       datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
        except OSError:
            pass
    return _migrate_legacy(business_name, index_path, storage_dir)


def list_batches(business_name: str, storage_dir: Optional[str] = None) -> List[Dict[str, str]]:
    index = ensure_library(business_name, storage_dir)
    return [dict(item) for item in index.get("batches", [])]


def get_active_batch(business_name: str,
                     storage_dir: Optional[str] = None) -> Optional[Dict[str, str]]:
    index = ensure_library(business_name, storage_dir)
    batches = index.get("batches", [])
    active_id = str(index.get("active") or "")
    for item in batches:
        if item.get("id") == active_id:
            return dict(item)
    return dict(batches[0]) if batches else None


def set_active_batch(business_name: str, batch_id: str,
                     storage_dir: Optional[str] = None) -> bool:
    index = ensure_library(business_name, storage_dir)
    if not any(item.get("id") == batch_id for item in index.get("batches", [])):
        return False
    index["active"] = batch_id
    _write_index(business_name, index, storage_dir)
    return True


def active_roster(business_name: str, storage_dir: Optional[str] = None) -> Roster:
    """读取当前活跃批次的名单；没有批次时自动建一个默认批次。"""
    batch = get_active_batch(business_name, storage_dir)
    if batch is None:
        batch = create_batch(business_name, DEFAULT_BATCH_NAME,
                             storage_dir=storage_dir)
    index = ensure_library(business_name, storage_dir)
    roster = Roster(
        business_name,
        key_field=str(index.get("key_field") or "姓名"),
        storage_path=_batch_file_path(business_name, batch["file"], storage_dir),
    )
    roster.batch_id = batch["id"]
    roster.batch_name = batch["name"]
    roster.load()
    if not roster.load_error and index.get("migration_error"):
        roster.load_error = str(index["migration_error"])
    return roster


def create_batch(business_name: str, name: str,
                 columns: Optional[Sequence[str]] = None,
                 key_field: str = "姓名",
                 incoming: Optional[Sequence[Dict[str, str]]] = None,
                 storage_dir: Optional[str] = None) -> Dict[str, str]:
    """新建批次并设为活跃；incoming 会在空批次上合并导入。"""
    index = ensure_library(business_name, storage_dir)
    clean_name = str(name or "").strip() or DEFAULT_BATCH_NAME
    existing = {str(item.get("name") or "") for item in index.get("batches", [])}
    if clean_name in existing:
        suffix = 2
        while f"{clean_name}({suffix})" in existing:
            suffix += 1
        clean_name = f"{clean_name}({suffix})"

    batch = _create_empty_batch(business_name, clean_name, key_field, storage_dir)
    roster = Roster(business_name, key_field=key_field,
                    storage_path=_batch_file_path(business_name, batch["file"], storage_dir))
    roster.load()
    if columns:
        roster.ensure_columns(columns)
    if incoming:
        roster.merge_rows(incoming)
    roster.save()

    index.setdefault("batches", []).append(batch)
    index["active"] = batch["id"]
    _write_index(business_name, index, storage_dir)
    return batch


def rename_batch(business_name: str, batch_id: str, new_name: str,
                 storage_dir: Optional[str] = None) -> bool:
    index = ensure_library(business_name, storage_dir)
    name = str(new_name or "").strip()
    if not name:
        return False
    for item in index.get("batches", []):
        if item.get("id") == batch_id:
            item["name"] = name
            _write_index(business_name, index, storage_dir)
            return True
    return False


def delete_batch(business_name: str, batch_id: str,
                 storage_dir: Optional[str] = None) -> bool:
    index = ensure_library(business_name, storage_dir)
    batches = index.get("batches", [])
    target = next((item for item in batches if item.get("id") == batch_id), None)
    if target is None:
        return False
    path = _batch_file_path(business_name, target.get("file", ""), storage_dir)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            return False
    index["batches"] = [item for item in batches if item.get("id") != batch_id]
    if str(index.get("active") or "") == batch_id:
        index["active"] = index["batches"][0]["id"] if index["batches"] else ""
    _write_index(business_name, index, storage_dir)
    return True

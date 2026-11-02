"""本机历史数据：按业务保存每次成功生成的数据，供“历史数据”回填。

只存变量值、自动编号和当时的输出目录，不存生成的 Word/Excel 文件本体。
文件：.docfill_state/history.json
"""

import datetime
import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from app_paths import APP_DIR

STATE_DIR_NAME = ".docfill_state"
HISTORY_FILE_NAME = "history.json"
MAX_PER_BUSINESS = 100
MAX_TOTAL = 2000


def _path(storage_path: Optional[str] = None) -> str:
    if storage_path:
        return storage_path
    return os.path.join(APP_DIR, STATE_DIR_NAME, HISTORY_FILE_NAME)


def _empty() -> Dict[str, Any]:
    return {"version": 1, "businesses": {}}


def _read(storage_path: Optional[str] = None) -> Dict[str, Any]:
    path = _path(storage_path)
    if not os.path.exists(path):
        return _empty()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("businesses", {})
    if not isinstance(data["businesses"], dict):
        data["businesses"] = {}
    return data


def _write(data: Dict[str, Any], storage_path: Optional[str] = None) -> None:
    path = _path(storage_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _clean_values(values: Dict[str, Any]) -> Dict[str, str]:
    cleaned = {}
    for key, value in (values or {}).items():
        if value is None:
            continue
        text = str(value)
        if text:
            cleaned[str(key)] = text
    return cleaned


def _fingerprint(values: Dict[str, str], auto_numbers: Dict[str, str]) -> str:
    payload = json.dumps(
        {"values": values, "auto_numbers": auto_numbers},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _prune(data: Dict[str, Any]) -> None:
    businesses = data.get("businesses", {})
    total = 0
    for business, records in list(businesses.items()):
        if not isinstance(records, list):
            businesses[business] = []
            continue
        records.sort(key=lambda r: str(r.get("time", "")), reverse=True)
        businesses[business] = records[:MAX_PER_BUSINESS]
        total += len(businesses[business])
    if total <= MAX_TOTAL:
        return
    # 全局超限：所有记录按时间排序，删最旧
    flat = []
    for business, records in businesses.items():
        for record in records:
            flat.append((str(record.get("time", "")), business, record))
    flat.sort(key=lambda item: item[0])
    for _time, business, record in flat[: max(0, total - MAX_TOTAL)]:
        if record in businesses.get(business, []):
            businesses[business].remove(record)


def append_history(
    business_name: str,
    values: Dict[str, Any],
    auto_numbers: Optional[Dict[str, str]] = None,
    name: str = "",
    id_tail: str = "",
    output_dir: str = "",
    storage_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """追加一条历史；完全相同的值只更新时间，不重复。"""
    business_name = str(business_name or "").strip()
    if not business_name:
        return None
    cleaned = _clean_values(values)
    auto = _clean_values(auto_numbers or {})
    if not cleaned and not auto:
        return None
    data = _read(storage_path)
    records = data["businesses"].setdefault(business_name, [])
    fingerprint = _fingerprint(cleaned, auto)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for record in records:
        if record.get("fingerprint") == fingerprint:
            record["time"] = now
            record["output_dir"] = output_dir or record.get("output_dir", "")
            _write(data, storage_path)
            return record
    record = {
        "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "time": now,
        "name": str(name or ""),
        "id_tail": str(id_tail or ""),
        "values": cleaned,
        "auto_numbers": auto,
        "output_dir": str(output_dir or ""),
        "fingerprint": fingerprint,
    }
    records.insert(0, record)
    _prune(data)
    _write(data, storage_path)
    return record


def load_history(business_name: str,
                 storage_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取某个业务的历史，最新在前。"""
    data = _read(storage_path)
    records = data.get("businesses", {}).get(str(business_name), [])
    return [dict(record) for record in records if isinstance(record, dict)]


def search_history(business_name: str, keyword: str,
                   storage_path: Optional[str] = None) -> List[Dict[str, Any]]:
    keyword = str(keyword or "").strip().lower()
    records = load_history(business_name, storage_path)
    if not keyword:
        return records
    result = []
    for record in records:
        text = " ".join([
            str(record.get("name", "")),
            str(record.get("id_tail", "")),
            " ".join(str(v) for v in record.get("values", {}).values()),
        ]).lower()
        if keyword in text:
            result.append(record)
    return result


def delete_record(business_name: str, record_id: str,
                  storage_path: Optional[str] = None) -> bool:
    data = _read(storage_path)
    records = data.get("businesses", {}).get(str(business_name), [])
    new_records = [r for r in records if r.get("id") != record_id]
    if len(new_records) == len(records):
        return False
    data["businesses"][str(business_name)] = new_records
    _write(data, storage_path)
    return True


def clear_history(business_name: Optional[str] = None,
                  storage_path: Optional[str] = None) -> int:
    data = _read(storage_path)
    if business_name:
        removed = len(data.get("businesses", {}).pop(str(business_name), []))
    else:
        removed = sum(len(v) for v in data.get("businesses", {}).values()
                      if isinstance(v, list))
        data = _empty()
    _write(data, storage_path)
    return removed


def history_size(storage_path: Optional[str] = None) -> int:
    path = _path(storage_path)
    try:
        return os.path.getsize(path)
    except OSError:
        return 0

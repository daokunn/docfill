"""本机用户状态：上次粘贴/生成的数据，按业务保存。

数据只保存在本机 ``.docfill_state/last_data.json``，用于“应用上次数据”。
不包含任何联网逻辑；用户可在设置里清除。
"""

import json
import os
from typing import Any, Dict, Optional

from app_paths import APP_DIR

STATE_DIR_NAME = ".docfill_state"
STATE_FILE_NAME = "last_data.json"


def _state_path(state_path: Optional[str] = None) -> str:
    if state_path:
        return state_path
    return os.path.join(APP_DIR, STATE_DIR_NAME, STATE_FILE_NAME)


def _read_all(state_path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    path = _state_path(state_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {}
    if not isinstance(data, dict):
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for business, values in data.items():
        if not isinstance(values, dict):
            continue
        cleaned = {}
        for key, value in values.items():
            if value is None:
                continue
            cleaned[str(key)] = str(value)
        if cleaned:
            result[str(business)] = cleaned
    return result


def _write_all(data: Dict[str, Any], state_path: Optional[str] = None) -> None:
    path = _state_path(state_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_last_data(business_name: str, state_path: Optional[str] = None) -> Dict[str, str]:
    """读取某个业务上次保存的数据；没有则返回空字典。"""
    if not business_name:
        return {}
    return dict(_read_all(state_path).get(str(business_name), {}))


def save_last_data(
    business_name: str,
    values: Dict[str, Any],
    state_path: Optional[str] = None,
) -> None:
    """保存某个业务的上次数据（覆盖旧记录）。"""
    if not business_name:
        return
    cleaned = {
        str(key): str(value)
        for key, value in (values or {}).items()
        if value is not None
    }
    if not cleaned:
        return
    data = _read_all(state_path)
    data[str(business_name)] = cleaned
    _write_all(data, state_path)


def clear_last_data(business_name: str, state_path: Optional[str] = None) -> None:
    """清除某个业务的上次数据。"""
    if not business_name:
        return
    data = _read_all(state_path)
    if str(business_name) in data:
        data.pop(str(business_name), None)
        _write_all(data, state_path)

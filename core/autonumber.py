"""自动编号（档案号 / 管理序号）。

场景：整理档案时档案号必须连续，但有些实物文档暂时没有，不能先占号造成断号。
所以编号在"真正生成文档时"才发放，只对实际产出的文件递增。

格式规则（用户需求）：
  无论前面混杂多少英文字母/符号，只把最后一段连续数字 +1，并保持原有位数。
  XJH202242312300001 -> XJH202242312300002
  A-0007             -> A-0008
  2024-001           -> 2024-002
  没有数字的            -> 原样追加 1

状态持久化在 .docfill_state/autonumber_<业务>.json，关软件不丢。
"""

import datetime
import json
import os
import re
from typing import Dict, List, Optional, Tuple

from app_paths import APP_DIR

STATE_DIR_NAME = ".docfill_state"
STATE_FILE_PREFIX = "autonumber_"

# 末尾连续数字（允许数字中间有分隔符时取最后一段）
_TRAILING_DIGITS = re.compile(r"(\d+)(?!.*\d)", re.S)


class NumberError(Exception):
    """编号配置或状态错误。"""


def split_number(text: str) -> Tuple[str, str]:
    """拆成 (前缀, 数字串)。没有数字时数字串为空。"""
    value = str(text or "").strip()
    match = _TRAILING_DIGITS.search(value)
    if not match:
        return value, ""
    return value[: match.start()], match.group(1)


def increment(text: str, step: int = 1) -> str:
    """把末尾数字 +step，保持补零位数；无数字则追加。"""
    prefix, digits = split_number(text)
    if not digits:
        return f"{prefix}{max(1, int(step))}"
    width = len(digits)
    value = int(digits) + int(step)
    return f"{prefix}{str(value).zfill(width)}"


def decrement(text: str) -> str:
    """把末尾数字 -1，保持补零位数；没有数字或已到 0 时返回空串。"""
    prefix, digits = split_number(text)
    if not digits:
        return ""
    value = int(digits) - 1
    if value < 0:
        return ""
    return f"{prefix}{str(value).zfill(len(digits))}"


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "").strip()) or "未命名业务"


def state_path(business_name: str, storage_dir: Optional[str] = None) -> str:
    folder = storage_dir or os.path.join(APP_DIR, STATE_DIR_NAME)
    return os.path.join(folder, f"{STATE_FILE_PREFIX}{_safe_name(business_name)}.json")


class AutoNumberBook:
    """一个业务的编号账本：记录每个变量最后发放的号码。"""

    def __init__(self, business_name: str, storage_path: Optional[str] = None):
        self.business_name = business_name
        self.storage_path = storage_path or state_path(business_name)
        # {field: {"seed": str, "last": str}}
        self.data: Dict[str, Dict[str, str]] = {}
        self.load_error: Optional[str] = None
        self.load()

    def load(self) -> None:
        self.data = {}
        self.load_error = None
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            self.load_error = f"编号状态读取失败：{exc}"
            return
        if not isinstance(raw, dict):
            return
        fields = raw.get("fields")
        if isinstance(fields, dict):
            for name, item in fields.items():
                if isinstance(item, dict):
                    self.data[str(name)] = {
                        "seed": str(item.get("seed") or ""),
                        "last": str(item.get("last") or ""),
                    }

    def save(self) -> bool:
        try:
            folder = os.path.dirname(self.storage_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            payload = {
                "_说明": "自动编号状态。last 是已发放的最后一个号码，seed 是用户设定的起始号。",
                "business": self.business_name,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "fields": self.data,
            }
            tmp = self.storage_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.storage_path)
        except OSError as exc:
            self.load_error = f"编号状态保存失败：{exc}"
            return False
        return True

    def configure(self, field: str, seed: str) -> None:
        """设定某变量的起始号；起始号变化时重置已发放记录。"""
        field = str(field or "").strip()
        seed = str(seed or "").strip()
        if not field:
            return
        record = self.data.setdefault(field, {"seed": "", "last": ""})
        old_seed = str(record.get("seed") or "")
        record["seed"] = seed
        if seed != old_seed:
            # 用户改了起始号，视为重新起号
            record["last"] = ""
            self.save()

    def peek(self, field: str) -> str:
        """查看下一个将要发放的号码（不消耗）。"""
        record = self.data.get(field) or {}
        last = str(record.get("last") or "").strip()
        seed = str(record.get("seed") or "").strip()
        if last:
            return increment(last)
        if seed:
            return seed
        return ""

    def consume(self, field: str) -> str:
        """发放下一个号码并立即落盘。没有配置起始号时返回空字符串。"""
        record = self.data.get(field) or {}
        last = str(record.get("last") or "").strip()
        seed = str(record.get("seed") or "").strip()
        if last:
            nxt = increment(last)
        elif seed:
            nxt = seed
        else:
            return ""
        self.data.setdefault(field, {"seed": seed, "last": ""})["last"] = nxt
        self.save()
        return nxt

    def rollback(self, field: str, previous: str) -> None:
        """生成失败时回退，避免占用号码造成断号。"""
        record = self.data.get(field)
        if record is None:
            return
        record["last"] = str(previous or "")
        self.save()

    def rollback_one(self, field: str) -> str:
        """回收最后一个已发放的号码；返回回收后的 last（空表示回到起始号之前）。"""
        record = self.data.get(field)
        if record is None:
            return ""
        last = str(record.get("last") or "").strip()
        seed = str(record.get("seed") or "").strip()
        if not last:
            return ""
        previous = decrement(last)
        # 已经退到起始号之前，就清空 last，让下一次重新从 seed 开始
        if seed:
            seed_prefix, seed_digits = split_number(seed)
            cur_prefix, cur_digits = split_number(previous)
            try:
                if (previous == "" or cur_prefix != seed_prefix
                        or int(cur_digits or 0) < int(seed_digits or 0)):
                    previous = ""
            except ValueError:
                pass
        record["last"] = previous
        self.save()
        return previous

    def set_last(self, field: str, value: str) -> None:
        """手动把"已发放的最后一个号"设为 value，下一次发放 value+1。"""
        record = self.data.setdefault(field, {"seed": "", "last": ""})
        record["last"] = str(value or "").strip()
        self.save()

    def current(self, field: str) -> str:
        """兼容别名：等同于 peek。"""
        return self.peek(field)

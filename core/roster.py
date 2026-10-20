"""人员名单（roster）存储与合并。

解决的问题：100 个人的资料不是一次到齐的。姓名、身份证号先有，贷款金额
过几天才定。所以名单必须常驻，并且支持"再来一批数据，按主键补进空白格"。

设计约定：
  - 名单存在本机 .docfill_state/roster_<业务名>.json，关软件、重启电脑都在
  - 每次改动立即落盘，不攒批；写入用 tmp + os.replace 原子替换，不会写坏
  - 名单是唯一真本，Excel/CSV 文件只是进出口：导入=合并进来，导出=写出去
  - 主键默认「姓名」，可按业务改（有些业务没有姓名，用别的唯一列）
  - 合并时非空值不静默覆盖已有值，冲突一律显式报出来让用户决定

不关心 UI、不处理文档生成。
"""

import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app_paths import APP_DIR

ROSTER_DIR_NAME = ".docfill_state"
ROSTER_FILE_PREFIX = "roster_"

# 名单行的状态
STATUS_PENDING = "pending"      # 有必填项没填完
STATUS_READY = "ready"          # 必填项已齐，还没生成文档
STATUS_GENERATED = "generated"  # 已经生成过文档


class RosterRow:
    """名单里的一行（一个人）。"""

    def __init__(self, values: Optional[Dict[str, str]] = None,
                 status: str = STATUS_PENDING,
                 generated_at: str = "", output_dir: str = ""):
        self.values: Dict[str, str] = dict(values or {})
        self.status = status or STATUS_PENDING
        self.generated_at = generated_at
        self.output_dir = output_dir

    def key_value(self, key_field: str) -> str:
        """取这一行的主键值（去掉首尾空格，便于比对）。"""
        return str(self.values.get(key_field, "") or "").strip()

    def missing_fields(self, required: Sequence[str]) -> List[str]:
        """返回必填项里仍为空的字段名，顺序沿用 required。"""
        missing = []
        for name in required:
            if not str(self.values.get(name, "") or "").strip():
                missing.append(name)
        return missing

    def display_name(self, key_field: str) -> str:
        """给用户看的行标识：主键值，没有就用状态兜底。"""
        value = self.key_value(key_field)
        return value or "（主键为空）"

    def to_dict(self) -> dict:
        return {
            "values": dict(self.values),
            "status": self.status,
            "generated_at": self.generated_at,
            "output_dir": self.output_dir,
        }

    @staticmethod
    def from_dict(data: Any) -> "RosterRow":
        """从文件里的字典还原一行，字段缺失或类型不对都不崩。"""
        if not isinstance(data, dict):
            return RosterRow()
        raw_values = data.get("values")
        values = {}
        if isinstance(raw_values, dict):
            for name, value in raw_values.items():
                if value is None:
                    continue
                values[str(name)] = str(value)
        return RosterRow(
            values=values,
            status=str(data.get("status") or STATUS_PENDING),
            generated_at=str(data.get("generated_at") or ""),
            output_dir=str(data.get("output_dir") or ""),
        )


class MergeResult:
    """一次导入合并的结果，用于给用户出报告。"""

    def __init__(self):
        self.added: List[RosterRow] = []                    # 新增的行
        self.updated: List[Tuple[int, List[str]]] = []      # (行下标, 被填的字段名)
        self.unchanged: int = 0                             # 匹配上了但没有新内容
        self.conflicts: List[Dict[str, str]] = []           # 值不一致，未覆盖
        self.ambiguous: List[Dict[str, Any]] = []           # 重名，无法定位到唯一行
        self.no_key: List[Dict[str, str]] = []              # 导入行缺主键值
        self.empty_cells_skipped: int = 0                   # 导入值为空而跳过的格子数
        self.new_columns: List[str] = []                    # 本次新出现的列

    @property
    def has_issues(self) -> bool:
        """是否有需要用户处理的情况。"""
        return bool(self.conflicts or self.ambiguous or self.no_key)

    def summary(self) -> str:
        """一句话摘要。"""
        parts = [f"新增 {len(self.added)} 人",
                 f"更新 {len(self.updated)} 人",
                 f"无变化 {self.unchanged} 人"]
        if self.conflicts:
            parts.append(f"冲突 {len(self.conflicts)} 处（未覆盖）")
        if self.ambiguous:
            parts.append(f"重名待确认 {len(self.ambiguous)} 行")
        if self.no_key:
            parts.append(f"缺主键 {len(self.no_key)} 行")
        if self.empty_cells_skipped:
            parts.append(f"跳过空格 {self.empty_cells_skipped} 个")
        return "；".join(parts)

    def detail_lines(self, limit: int = 20) -> List[str]:
        """展开明细，供报告弹窗展示。"""
        lines: List[str] = []

        if self.conflicts:
            lines.append("以下值与名单中已有数据不一致，已保留原值、未覆盖：")
            for item in self.conflicts[:limit]:
                lines.append(
                    f"  {item['row']} 的「{item['field']}」："
                    f"名单里是「{item['current']}」，导入的是「{item['incoming']}」")
            if len(self.conflicts) > limit:
                lines.append(f"  …… 另有 {len(self.conflicts) - limit} 处")
            lines.append("")

        if self.ambiguous:
            lines.append("以下导入行在名单里匹配到多条（重名），无法确定该补给哪一条，未合并：")
            for item in self.ambiguous[:limit]:
                candidates = "、".join(
                    f"第{index + 1}行" for index in item.get("matches", []))
                lines.append(f"  「{item['key']}」匹配到 {candidates}")
            if len(self.ambiguous) > limit:
                lines.append(f"  …… 另有 {len(self.ambiguous) - limit} 行")
            lines.append("  请在名单窗口里搜索这些人，逐个手动填写；"
                         "或改用身份证号等唯一列作为匹配依据。")
            lines.append("")

        if self.no_key:
            lines.append("以下导入行没有主键值，无法定位，未合并：")
            for item in self.no_key[:limit]:
                preview = "、".join(f"{k}={v}" for k, v in list(item.items())[:3])
                lines.append(f"  {preview}")
            if len(self.no_key) > limit:
                lines.append(f"  …… 另有 {len(self.no_key) - limit} 行")

        return lines


class Roster:
    """一个业务的人员名单。"""

    def __init__(self, business_name: str, key_field: str = "姓名",
                 storage_path: Optional[str] = None):
        self.business_name = str(business_name or "")
        self.key_field = str(key_field or "姓名").strip() or "姓名"
        self.columns: List[str] = []
        self.rows: List[RosterRow] = []
        self.storage_path = storage_path or roster_path(self.business_name)
        self.load_error: Optional[str] = None

    # ---------- 持久化 ----------

    def load(self) -> "Roster":
        """从磁盘读取名单。文件不存在返回空名单；损坏时记录错误但不抛异常。

        名单里有用户辛苦补录的数据，读坏了也不能让软件崩，
        但必须把错误暴露出来（load_error），否则用户会以为数据丢了。
        """
        self.load_error = None
        self.columns = []
        self.rows = []

        if not os.path.exists(self.storage_path):
            return self
        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            self.load_error = f"名单文件读取失败：{exc}"
            return self

        if not isinstance(data, dict):
            self.load_error = "名单文件格式不正确（顶层应为对象）"
            return self

        raw_columns = data.get("columns")
        if isinstance(raw_columns, list):
            self.columns = [str(c).strip() for c in raw_columns if str(c).strip()]

        key_field = str(data.get("key_field") or "").strip()
        if key_field:
            self.key_field = key_field

        raw_rows = data.get("rows")
        if isinstance(raw_rows, list):
            self.rows = [RosterRow.from_dict(item) for item in raw_rows]
        return self

    def save(self) -> bool:
        """立即落盘。返回是否成功；失败原因记在 load_error。

        用户最担心的是"关掉软件数据就没了"，所以每次改动都马上写，
        不做攒批保存。写入先落 tmp 再 os.replace，中途断电也不会留半截文件。
        """
        payload = {
            "_说明": (
                "人员名单数据，由「人员名单」窗口维护，关软件和重启电脑都不会丢失。"
                "key_field 是匹配用的主键列；status: pending=待补充, ready=已填完, "
                "generated=已生成文档。建议不要手工编辑本文件，改动请通过界面进行。"
            ),
            "business": self.business_name,
            "key_field": self.key_field,
            "columns": list(self.columns),
            "rows": [row.to_dict() for row in self.rows],
        }
        try:
            folder = os.path.dirname(self.storage_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp_path = self.storage_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.storage_path)
        except OSError as exc:
            self.load_error = f"名单保存失败：{exc}"
            return False
        self.load_error = None
        return True

    # ---------- 列管理 ----------

    def ensure_columns(self, names: Sequence[str]) -> List[str]:
        """把新列名并进 columns（保持原有顺序），返回本次新增的列。"""
        added = []
        for name in names:
            name = str(name or "").strip()
            if name and name not in self.columns:
                self.columns.append(name)
                added.append(name)
        return added

    def set_key_field(self, key_field: str) -> None:
        """切换主键列。列不存在时自动补上，避免主键指向一个不存在的列。"""
        key_field = str(key_field or "").strip()
        if not key_field:
            return
        self.key_field = key_field
        self.ensure_columns([key_field])

    # ---------- 查询 ----------

    def duplicate_keys(self) -> Dict[str, List[int]]:
        """找出主键重复的行：{主键值: [行下标...]}，只返回出现 2 次以上的。

        重名不是错误，但必须让用户看见——否则按姓名补数据时可能补错人。
        """
        buckets: Dict[str, List[int]] = {}
        for index, row in enumerate(self.rows):
            key = row.key_value(self.key_field)
            if not key:
                continue
            buckets.setdefault(key, []).append(index)
        return {key: indexes for key, indexes in buckets.items() if len(indexes) > 1}

    def find_matches(self, key_value: str) -> List[int]:
        """按主键值找行下标。"""
        target = str(key_value or "").strip()
        if not target:
            return []
        return [index for index, row in enumerate(self.rows)
                if row.key_value(self.key_field) == target]

    def search(self, keyword: str) -> List[int]:
        """跨所有列搜索，返回命中的行下标。"""
        keyword = str(keyword or "").strip().lower()
        if not keyword:
            return list(range(len(self.rows)))
        hits = []
        for index, row in enumerate(self.rows):
            if any(keyword in str(value).lower() for value in row.values.values()):
                hits.append(index)
        return hits

    def required_fields(self, template_vars: Sequence[str],
                        optional_vars: Sequence[str]) -> List[str]:
        """必填列 = 模板变量 - 可选变量，顺序沿用模板变量顺序。

        可选性只认模板里的 {{备注?}} 写法，名单不另搞一套标记，
        否则两个地方都能定义"备注是否必填"，迟早不一致。
        """
        optional = {str(name).strip() for name in optional_vars}
        return [str(name).strip() for name in template_vars
                if str(name).strip() and str(name).strip() not in optional]

    def refresh_status(self, required: Sequence[str]) -> None:
        """按必填项重算每行状态；已生成的行保持 generated 不退回。"""
        for row in self.rows:
            if row.status == STATUS_GENERATED:
                continue
            row.status = STATUS_READY if not row.missing_fields(required) else STATUS_PENDING

    def counts(self, required: Sequence[str]) -> Dict[str, int]:
        """统计各状态行数，供界面底部显示。"""
        pending = ready = generated = 0
        for row in self.rows:
            if row.status == STATUS_GENERATED:
                generated += 1
            elif row.missing_fields(required):
                pending += 1
            else:
                ready += 1
        return {"total": len(self.rows), "pending": pending,
                "ready": ready, "generated": generated}

    # ---------- 合并导入 ----------

    def merge_rows(self, incoming: Sequence[Dict[str, str]],
                   match_field: str = "",
                   overwrite_conflicts: bool = False) -> MergeResult:
        """把一批数据按主键合并进名单。

        :param incoming: 每行是 {列名: 值}，来自 Excel/CSV 导入
        :param match_field: 用哪一列匹配名单主键。留空表示导入文件里的列名
            和名单主键同名；如果文件里没有姓名列、只有证件号码，就传 "证件号码"。
        :param overwrite_conflicts: True 时冲突值覆盖名单原值，默认 False（保留原值）

        合并规则（逐格判断）：
          导入值为空          -> 不动（关键：第二批文件常缺列，不能把已有值清空）
          名单里是空          -> 填入
          两边相同            -> 跳过
          两边不同            -> 记为冲突，默认不覆盖

        主键匹配到多行（重名）时不猜，记入 ambiguous 让用户自己处理。
        """
        result = MergeResult()
        if not incoming:
            return result

        match_field = str(match_field or "").strip()
        # 用哪一列去匹配名单。留空表示导入文件的列名和名单主键同名；
        # 名单主键是「姓名」，但贷款金额表里只有「身份证号」时，就传身份证号。
        source_field = match_field or self.key_field

        # 收集本批数据里出现的所有列，先并进 columns
        all_columns: List[str] = []
        for item in incoming:
            for name in item:
                name = str(name).strip()
                if name and name not in all_columns:
                    all_columns.append(name)
        result.new_columns = self.ensure_columns(all_columns)
        self.ensure_columns([self.key_field, source_field])

        # 匹配列的值 -> 行下标 索引。
        # 两点很关键：
        #   1. 索引建在 source_field 上而不是 key_field：用身份证号匹配时，
        #      若仍按姓名建索引会一个都匹配不上，把已有的人当成新人重复建。
        #   2. 索引是"批次开始前"的快照，本批新增的行不进索引。否则同一个
        #      文件里的第二个张三会被并进第一个张三，两个人的数据混成一个人。
        index_by_key: Dict[str, List[int]] = {}
        for position, row in enumerate(self.rows):
            key = str(row.values.get(source_field, "") or "").strip()
            if key:
                index_by_key.setdefault(key, []).append(position)

        # 本批已消费过的匹配值。同一个值在文件里出现第二次，说明是两个
        # 同名的人，应当各自成行，而不是合并或丢弃。
        used_keys: set = set()

        for item in incoming:
            cleaned = {str(k).strip(): str(v or "").strip()
                       for k, v in item.items() if str(k).strip()}
            key = cleaned.get(source_field, "")

            if not key:
                result.no_key.append(cleaned)
                continue

            matches = index_by_key.get(key, [])

            if len(matches) > 1:
                # 名单里有多条同值（重名），无法判断该补给谁，不猜
                result.ambiguous.append({"key": key, "matches": list(matches),
                                         "values": cleaned})
                continue

            if len(matches) == 1 and key not in used_keys:
                changed = self._merge_into(self.rows[matches[0]], cleaned,
                                           result, overwrite_conflicts)
                used_keys.add(key)
                if changed:
                    result.updated.append((matches[0], changed))
                else:
                    result.unchanged += 1
                continue

            # 名单里没有这个人，或本批已经处理过一个同值的行 -> 新增一行。
            # 重名是允许的：两个张三身份证号不同就是两个人，
            # 名单窗口会把重名一并显示出来提醒用户。
            new_row = RosterRow()
            for name, value in cleaned.items():
                if value:
                    new_row.values[name] = value
            self.rows.append(new_row)
            used_keys.add(key)
            result.added.append(new_row)

        return result

    def _merge_into(self, row: RosterRow, cleaned: Dict[str, str],
                    result: MergeResult,
                    overwrite_conflicts: bool) -> List[str]:
        """把一行导入数据合并进已有名单行，返回被填入的字段名。

        值一律写进同名列。这里刻意不做"把匹配列的值搬到主键列"之类的
        列名重映射：别名归一（证件号码 -> 身份证号）属于导入层的职责，
        在核心层猜列名对应关系，猜错就会拿身份证号覆盖掉姓名。
        """
        changed: List[str] = []
        for target, value in cleaned.items():
            if not value:
                # 导入值为空：绝不清空名单里已有的值
                result.empty_cells_skipped += 1
                continue

            current = str(row.values.get(target, "") or "").strip()
            if not current:
                row.values[target] = value
                changed.append(target)
            elif current == value:
                continue
            else:
                if overwrite_conflicts:
                    row.values[target] = value
                    changed.append(target)
                else:
                    result.conflicts.append({
                        "row": row.display_name(self.key_field),
                        "field": target,
                        "current": current,
                        "incoming": value,
                    })
        return changed

    # ---------- 增删改 ----------

    def add_row(self, values: Optional[Dict[str, str]] = None) -> RosterRow:
        """新增一个空白行。"""
        row = RosterRow(values=values)
        self.rows.append(row)
        self.ensure_columns(list(row.values))
        return row

    def remove_rows(self, indexes: Sequence[int]) -> int:
        """按下标删除若干行，返回实际删除数量。"""
        keep = set(int(i) for i in indexes if 0 <= int(i) < len(self.rows))
        if not keep:
            return 0
        self.rows = [row for index, row in enumerate(self.rows) if index not in keep]
        return len(keep)

    def missing_columns(self, present: Sequence[str]) -> List[str]:
        """返回名单里有、但本次导入文件里没有的列（供"是否删除消失列"询问）。"""
        present_set = {str(name).strip() for name in present if str(name).strip()}
        gone = [name for name in self.columns if name and name not in present_set]
        # 主键列永远保留，否则整份名单无法匹配
        return [name for name in gone if name != self.key_field]

    def drop_columns(self, names: Sequence[str]) -> int:
        """删除指定列（从列清单和每行数据里移除），返回删除数量。"""
        targets = {str(name).strip() for name in names if str(name).strip()}
        targets.discard(self.key_field)  # 主键不可删
        if not targets:
            return 0
        self.columns = [name for name in self.columns if name not in targets]
        for row in self.rows:
            for name in targets:
                row.values.pop(name, None)
        return len(targets)

    def set_value(self, index: int, column: str, value: str) -> bool:
        """改某个格子的值。"""
        if not 0 <= index < len(self.rows):
            return False
        column = str(column or "").strip()
        if not column:
            return False
        self.ensure_columns([column])
        text = str(value or "").strip()
        if text:
            self.rows[index].values[column] = text
        else:
            self.rows[index].values.pop(column, None)
        return True

    def mark_generated(self, indexes: Sequence[int], output_dirs: Optional[Dict[int, str]] = None) -> None:
        """标记若干行已生成文档。"""
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        dirs = output_dirs or {}
        for index in indexes:
            if 0 <= int(index) < len(self.rows):
                self.rows[int(index)].status = STATUS_GENERATED
                self.rows[int(index)].generated_at = stamp
                if int(index) in dirs:
                    self.rows[int(index)].output_dir = str(dirs[int(index)])

    def reset_generated(self, indexes: Sequence[int]) -> None:
        """把若干行的"已生成"标记撤掉，状态按必填项重算。"""
        for index in indexes:
            if 0 <= int(index) < len(self.rows):
                self.rows[int(index)].status = STATUS_PENDING
                self.rows[int(index)].generated_at = ""

    # ---------- 导出 ----------

    def to_table(self, columns: Optional[Sequence[str]] = None) -> List[List[str]]:
        """导出为二维表（含表头行），供写 Excel/CSV 或界面展示。"""
        header = [str(c) for c in (columns or self.columns)]
        table = [header]
        for row in self.rows:
            table.append([str(row.values.get(name, "") or "") for name in header])
        return table

    def selected_dicts(self, indexes: Sequence[int],
                       columns: Optional[Sequence[str]] = None) -> List[Dict[str, str]]:
        """把指定行导出为 {列名: 值} 列表，形状正好是批量生成要的输入。"""
        names = [str(c) for c in (columns or self.columns)]
        output = []
        for index in indexes:
            if not 0 <= int(index) < len(self.rows):
                continue
            row = self.rows[int(index)]
            output.append({name: str(row.values.get(name, "") or "") for name in names})
        return output


# ---------- 文件路径 ----------

def _sanitize_business_name(name: str) -> str:
    """业务名转成安全的文件名片段。"""
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "").strip())
    return text.strip("._") or "未命名业务"


def roster_path(business_name: str, storage_dir: Optional[str] = None) -> str:
    """名单文件路径：.docfill_state/roster_<业务名>.json。

    和「上次数据」放在同一个目录，都是本机持久化数据，
    用户可以在设置里一起清除。
    """
    folder = storage_dir or os.path.join(APP_DIR, ROSTER_DIR_NAME)
    filename = f"{ROSTER_FILE_PREFIX}{_sanitize_business_name(business_name)}.json"
    return os.path.join(folder, filename)


def load_roster(business_name: str, key_field: str = "姓名",
                storage_path: Optional[str] = None) -> Roster:
    """读取（或新建）某个业务的名单。"""
    roster = Roster(business_name=business_name, key_field=key_field,
                    storage_path=storage_path)
    roster.load()
    return roster


def list_saved_businesses(storage_dir: Optional[str] = None) -> List[Tuple[str, str]]:
    """列出本机已保存的名单：[(业务名, 文件路径)]，按修改时间倒序。

    业务名从文件内容里读，比从文件名反推可靠（文件名做过字符清理）。
    """
    folder = storage_dir or os.path.join(APP_DIR, ROSTER_DIR_NAME)
    if not os.path.isdir(folder):
        return []

    entries = []
    for name in os.listdir(folder):
        if not name.startswith(ROSTER_FILE_PREFIX) or not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        business = ""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                business = str(data.get("business") or "")
        except (json.JSONDecodeError, OSError):
            business = ""
        if not business:
            business = name[len(ROSTER_FILE_PREFIX):-len(".json")]
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        entries.append((mtime, business, path))

    entries.sort(key=lambda item: item[0], reverse=True)
    return [(business, path) for _mtime, business, path in entries]

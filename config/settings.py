"""
全局配置管理模块
负责读写 settings.json，管理模板根目录、输出根目录、重名策略等全局参数。
不依赖任何业务逻辑，纯配置读写。
"""

import json
import os
from typing import Any, Dict, Optional

from app_paths import config_path

# 配置文件路径：打包后位于 exe 同目录的 config/ 下（可持久化），开发时位于本文件同目录
SETTINGS_FILE = config_path("settings.json", writable=True)

# 默认配置
DEFAULT_SETTINGS: Dict[str, Any] = {
    "template_root_dir": "",          # 模板根目录（用户设置）
    "output_root_dir": "",            # 输出根目录（用户设置，与模板物理隔离）
    "theme": "ink",                   # 界面主题：ink / light / dark / sepia
    "rename_strategy": "append_seq",  # 重名策略：append_seq / overwrite / skip
    "customer_var": "客户名",         # 客户名变量名（用于输出子文件夹命名）
    "id_card_var": "身份证号",        # 身份证号变量名（用于重名去重，取后四位）
    "date_format": "YYYY年M月D日",     # 日期写入文档时的格式
    "date_range_separator": "至",      # 起止日期连接词
    "variable_order": "smart",        # template / smart / alphabetical / custom
    "order_migrated": False,           # 旧配置一次性迁移到智能分组
    "custom_variable_order": {},       # {业务名: [变量名顺序]}，拖拽后保存
    "show_variable_groups": True,      # 变量表显示“分组”列并按组着色
    "clear_after_generate": False,     # 生成完成后是否自动清空变量表
    "open_folder_after_generate": True,  # 生成完成后自动打开输出文件夹
    "open_generated_files": False,     # 生成后自动打开本次生成的文件
    "open_files_mode": "all",          # all / first / specified
    "open_files_templates": [],        # 指定打开哪些模板生成的文件（可多选）
    "open_files_specified": "",        # 兼容旧配置：单个指定文件路径或文件名
    "auto_print_after_open": False,    # 打开后自动打印
    "silent_print": False,             # 静默打印默认关闭：先弹打印对话框，避免误打整批
    "print_copies": 1,                 # 每个文件打印份数
    "printer_name": "",                # 指定打印机；空=系统默认
    "handover_enabled": True,          # 是否维护移交清单台账
    "handover_template": "",           # 汇总模板 xlsx 路径；空则自动生成标准表头
    "handover_dedup_field": "姓名",     # 移交清单去重/匹配用的列
    "shrink_overflow_font": True,      # 单元格内容溢出时允许缩小字号保住页数
    "strip_invisible_chars": True,     # 输入/粘贴时自动去除零宽空格等不可见字符
    "validation_enabled": True,        # 生成前变量校验（身份证/手机号/自定义正则），默认开启
    "validation_builtin_enabled": True, # 内置预设按变量名自动套用（身份证/手机号/邮箱），无需配置
    "smart_paste_splitter": [],        # 智能粘贴窗口输入区/结果区的分隔位置（可拖动）
    "batch_import_mode": "new_batch",  # 批量导入：new_batch / merge_current / ask
    "number_manual_mode": "once",      # 手动改编号：once(仅本次) / book(改账本下一号)
    "date_format_overrides": {},       # {变量名: 日期格式}，按变量覆盖全局格式
    "auto_number_fields": {},          # 自动编号：{变量名: 起始号}，可多选
    "directory_history": {},           # {业务名: {"template": [...], "output": [...]}}
    "log_filename": "operation.log",  # 操作日志文件名
    # 快捷键配置
    "shortcuts": {
        "smart_paste": "Ctrl+Shift+V",   # 智能粘贴解析
        "generate": "Ctrl+G",            # 一键生成文档
        "rescan": "F5",                  # 重新扫描模板
        "reuse": "Ctrl+R",               # 应用上次数据
        "next_case": "Ctrl+N",           # 下一单（清空）
        "open_output": "Ctrl+O",         # 打开输出目录
        "import": "Ctrl+I",              # 批量：导入名单
        "generate_selected": "Ctrl+Shift+G",  # 批量：生成选中
        "delete_rows": "Ctrl+Delete",            # 批量：删除选中行
        "export": "Ctrl+E",              # 批量：导出名单
        "bulk_set": "Ctrl+Shift+F",      # 批量：批量设值
    },
}


def migrate_legacy_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """把老配置里已知的不安全默认值一次性迁移到新默认值。

    只针对"确实是旧默认值"的情况；用户自己改过的选择一律保留。
    用 _safety_migrated 标记保证只迁移一次，之后完全尊重用户设置。
    """
    out = dict(data or {})
    if out.get("_safety_migrated"):
        return out
    shortcuts = out.get("shortcuts")
    if isinstance(shortcuts, dict):
        if str(shortcuts.get("delete_rows", "")).strip() in ("Del", "Delete"):
            shortcuts = dict(shortcuts)
            shortcuts["delete_rows"] = "Ctrl+Delete"
            out["shortcuts"] = shortcuts
    # 静默打印默认由开改为关（批量窗口已不再提供该开关，避免不知情误打整批）
    if out.get("silent_print") is True:
        out["silent_print"] = False
    out["_safety_migrated"] = True
    return out


class Settings:
    """全局配置单例"""

    _instance: Optional["Settings"] = None

    def __new__(cls) -> "Settings":
        """单例模式：首次调用时加载配置，后续调用返回同一实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = dict(DEFAULT_SETTINGS)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        """从磁盘加载配置，不存在则创建默认"""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 合并：以默认值为底，用已保存值覆盖
                self._data.update(saved)
                # 快捷键是嵌套字典：老配置文件没有新键，必须逐键补齐，
                # 否则升级后新快捷键会静默失效。
                saved_shortcuts = saved.get("shortcuts")
                if isinstance(saved_shortcuts, dict):
                    merged = dict(DEFAULT_SETTINGS.get("shortcuts", {}))
                    merged.update(saved_shortcuts)
                    self._data["shortcuts"] = merged
                # 老配置的安全默认值一次性迁移（删除键/静默打印）
                self._data = migrate_legacy_settings(self._data)
                if saved != self._data:
                    self.save()
            except (json.JSONDecodeError, IOError):
                # 配置文件损坏则回退到默认值，不影响启动
                self._data = dict(DEFAULT_SETTINGS)
                self.save()
        else:
            self.save()

    def reload(self) -> None:
        """从磁盘重新加载（配置恢复后调用）。"""
        self._data = dict(DEFAULT_SETTINGS)
        self._load()

    def save(self) -> None:
        """保存配置到磁盘"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            raise IOError(f"配置文件保存失败：{e}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取单个配置项，不存在则返回 default"""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置单个配置项并立即持久化到磁盘"""
        self._data[key] = value
        self.save()

    def update(self, items: Dict[str, Any]) -> None:
        """批量更新配置项并持久化"""
        self._data.update(items)
        self.save()

    @property
    def template_root_dir(self) -> str:
        """模板根目录路径"""
        return self._data.get("template_root_dir", "")

    @template_root_dir.setter
    def template_root_dir(self, value: str) -> None:
        """设置模板根目录路径"""
        self.set("template_root_dir", value)

    @property
    def output_root_dir(self) -> str:
        """输出根目录路径（与模板物理隔离）"""
        return self._data.get("output_root_dir", "")

    @output_root_dir.setter
    def output_root_dir(self, value: str) -> None:
        """设置输出根目录路径"""
        self.set("output_root_dir", value)

    @property
    def rename_strategy(self) -> str:
        """重名策略：append_seq（追加序号）/ overwrite（覆盖）/ skip（跳过）"""
        return self._data.get("rename_strategy", "append_seq")

    @rename_strategy.setter
    def rename_strategy(self, value: str) -> None:
        """设置重名策略，仅允许 append_seq/overwrite/skip"""
        if value not in ("append_seq", "overwrite", "skip"):
            raise ValueError(f"无效的重名策略：{value}，可选 append_seq/overwrite/skip")
        self.set("rename_strategy", value)

    def business_directory(self, business_name: str) -> Dict[str, Any]:
        """某个业务上次使用的模板/输出目录及近期历史。"""
        name = str(business_name or "").strip()
        history = self._data.get("directory_history", {}) or {}
        if not isinstance(history, dict):
            return {"template": [], "output": []}
        item = history.get(name, {}) if name else {}
        if not isinstance(item, dict):
            return {"template": [], "output": []}
        result = {}
        for kind in ("template", "output"):
            values = item.get(kind, [])
            if isinstance(values, str):
                values = [values]
            result[kind] = [str(v) for v in values if str(v).strip()][:12]
        return result

    def remember_business_directory(self, business_name: str,
                                    template_dir: str, output_dir: str) -> None:
        """记住业务路径，并把最近使用的目录放到最前面。"""
        name = str(business_name or "").strip()
        if not name:
            return
        history = self._data.get("directory_history", {})
        if not isinstance(history, dict):
            history = {}
        item = history.get(name, {})
        if not isinstance(item, dict):
            item = {}
        for kind, value in (("template", template_dir), ("output", output_dir)):
            value = str(value or "").strip()
            values = item.get(kind, [])
            if isinstance(values, str):
                values = [values]
            values = [str(v) for v in values if str(v).strip()]
            if value:
                values = [value] + [v for v in values if v != value]
            item[kind] = values[:12]
        history[name] = item
        self._data["directory_history"] = history
        self.save()

    def recent_directories(self, kind: str, business_name: str = "") -> list:
        """当前业务历史 + 所有业务历史，供目录窗口快速选择。"""
        merged = []
        current = self.business_directory(business_name)
        merged.extend(current.get(kind, []))
        history = self._data.get("directory_history", {}) or {}
        if isinstance(history, dict):
            for item in history.values():
                if isinstance(item, dict):
                    values = item.get(kind, [])
                    if isinstance(values, str):
                        values = [values]
                    merged.extend(str(v) for v in values if str(v).strip())
        result = []
        for value in merged:
            if value not in result:
                result.append(value)
        return result[:12]

    def to_dict(self) -> Dict[str, Any]:
        """返回配置的字典副本，用于展示"""
        return dict(self._data)


# 便捷全局访问
def get_settings() -> Settings:
    """获取全局配置单例实例"""
    return Settings()

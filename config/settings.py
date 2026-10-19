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
    "rename_strategy": "append_seq",  # 重名策略：append_seq / overwrite / skip
    "customer_var": "客户名",         # 客户名变量名（用于输出子文件夹命名）
    "id_card_var": "身份证号",        # 身份证号变量名（用于重名去重，取后四位）
    "date_format": "YYYY年M月D日",     # 日期写入文档时的格式
    "date_range_separator": "至",      # 起止日期连接词
    "variable_order": "template",      # 变量表顺序：template（填写顺序）/ alphabetical（字典序）
    "clear_after_generate": False,     # 生成完成后是否自动清空变量表
    "shrink_overflow_font": True,      # 单元格内容溢出时允许缩小字号保住页数
    "log_filename": "operation.log",  # 操作日志文件名
    # 快捷键配置
    "shortcuts": {
        "smart_paste": "Ctrl+Shift+V",   # 智能粘贴解析
        "generate": "Ctrl+G",            # 一键生成文档
        "rescan": "F5",                  # 重新扫描模板
        "reuse": "Ctrl+R",               # 应用上次数据
    },
}


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
            except (json.JSONDecodeError, IOError):
                # 配置文件损坏则回退到默认值，不影响启动
                self._data = dict(DEFAULT_SETTINGS)
                self.save()
        else:
            self.save()

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

    def to_dict(self) -> Dict[str, Any]:
        """返回配置的字典副本，用于展示"""
        return dict(self._data)


# 便捷全局访问
def get_settings() -> Settings:
    """获取全局配置单例实例"""
    return Settings()

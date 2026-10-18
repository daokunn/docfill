"""
变量名别名映射模块
职责：
  1. 加载 config/aliases.json 中的别名映射表
  2. 提供"别名 -> 标准标签"的归一化查询
  3. 支持用户动态添加别名并持久化
不关心 UI、不处理文档。
"""

import json
import os
from typing import Dict, List, Optional

from app_paths import config_path

# 别名文件路径：打包后位于 exe 同目录 config/ 下（用户新增别名可持久化），首次运行自动释放内置初始数据
ALIASES_FILE = config_path("aliases.json", writable=True)


class AliasMapper:
    """变量名别名映射器"""

    def __init__(self, aliases_path: str = ALIASES_FILE):
        """加载别名映射表，构建反向索引"""
        self.aliases_path = aliases_path
        # {标准标签: [别名列表]}
        self.aliases: Dict[str, List[str]] = {}
        # {别名: 标准标签} 反向索引
        self._reverse: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """从 aliases.json 加载别名映射"""
        if not os.path.exists(self.aliases_path):
            return
        try:
            with open(self.aliases_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 过滤掉以 _ 开头的说明字段
            self.aliases = {k: v for k, v in data.items()
                            if not k.startswith("_") and isinstance(v, list)}
            self._rebuild_reverse()
        except (json.JSONDecodeError, IOError):
            pass

    def _rebuild_reverse(self) -> None:
        """根据 aliases 重建反向索引"""
        self._reverse = {}
        for standard, alias_list in self.aliases.items():
            for alias in alias_list:
                self._reverse[alias] = standard

    def normalize(self, name: str) -> str:
        """
        将变量名归一化为系统标准标签。
        如果 name 是某个标准标签的别名，返回标准标签；否则返回原名。
        """
        if not name:
            return name
        # 自身就是标准标签
        if name in self.aliases:
            return name
        # 是某个标准标签的别名
        return self._reverse.get(name, name)

    def get_standard_names(self) -> List[str]:
        """返回所有系统标准标签名"""
        return list(self.aliases.keys())

    def get_aliases(self, standard: str) -> List[str]:
        """获取某个标准标签的所有别名（不含自身）"""
        return self.aliases.get(standard, [])

    def add_alias(self, standard: str, alias: str) -> bool:
        """
        为标准标签添加一个别名。
        :return: 是否添加成功（别名已存在则返回 False）
        """
        if not standard or not alias or standard == alias:
            return False
        if standard not in self.aliases:
            self.aliases[standard] = []
        if alias in self.aliases[standard]:
            return False
        self.aliases[standard].append(alias)
        self._reverse[alias] = standard
        return True

    def save(self) -> None:
        """将别名映射保存回 aliases.json"""
        # 保留说明字段
        existing = {}
        if os.path.exists(self.aliases_path):
            try:
                with open(self.aliases_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        # 合并：保留 _ 开头的说明字段
        output = {k: v for k, v in existing.items() if k.startswith("_")}
        output.update(self.aliases)
        os.makedirs(os.path.dirname(self.aliases_path), exist_ok=True)
        with open(self.aliases_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)


# 全局单例
_instance: Optional[AliasMapper] = None


def get_alias_mapper() -> AliasMapper:
    """获取全局 AliasMapper 单例"""
    global _instance
    if _instance is None:
        _instance = AliasMapper()
    return _instance

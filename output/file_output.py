"""
文件输出 & 日志模块
职责：
  1. 管理输出根目录（与模板物理隔离）
  2. 生成业务输出子文件夹：业务名_客户名_年月
  3. 还原模板内部目录结构
  4. 重名策略：追加序号_身份证后四位 / 覆盖 / 跳过
  5. 生成操作日志
不处理模板内容、不处理 UI。
"""

import datetime
import logging
import os
import re
from typing import Dict, Optional

from config.settings import get_settings


class OutputError(Exception):
    """输出模块错误"""
    pass


class OutputManager:
    """文件输出管理器"""

    def __init__(self):
        """文件输出管理器"""
        self.settings = get_settings()            # 全局配置实例
        self._logger: Optional[logging.Logger] = None  # 操作日志 logger（延迟创建）

    @property
    def output_root(self) -> str:
        """输出根目录路径"""
        return self.settings.output_root_dir

    def ensure_output_root(self) -> str:
        """确保输出根目录存在，返回路径。不存在则创建，无权限则抛错。"""
        root = self.output_root
        if not root:
            raise OutputError("未设置输出目录，请先在设置中配置输出路径")
        try:
            if not os.path.exists(root):
                os.makedirs(root, exist_ok=True)
            # 测试写入权限
            test_file = os.path.join(root, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except PermissionError:
            raise OutputError(f"输出目录无写入权限：{root}")
        except OSError as e:
            raise OutputError(f"输出目录创建失败：{e}")
        return root

    def build_subfolder_name(self, business_name: str, variables: Dict[str, str]) -> str:
        """
        生成业务输出子文件夹名称：业务名_客户名_年月
        客户名为空时兜底为"未知客户"。
        """
        customer_var = self.settings.get("customer_var", "客户名")
        customer_name = str(variables.get(customer_var, "")).strip()
        if not customer_name:
            customer_name = "未知客户"
        # 清理文件名非法字符
        customer_name = _sanitize_filename(customer_name)
        year_month = datetime.date.today().strftime("%Y%m")
        return f"{business_name}_{customer_name}_{year_month}"

    def get_output_dir(self, business_name: str, variables: Dict[str, str]) -> str:
        """获取（并创建）业务输出子文件夹的完整路径"""
        root = self.ensure_output_root()
        folder_name = self.build_subfolder_name(business_name, variables)
        output_dir = os.path.join(root, folder_name)
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    def resolve_output_path(self, template_rel_path: str, output_dir: str,
                            variables: Dict[str, str]) -> str:
        """
        根据模板相对路径，在输出目录中还原目录结构，并应用重名策略。
        :param template_rel_path: 模板相对于业务文件夹的相对路径
        :param output_dir: 业务输出子文件夹路径
        :param variables: 变量字典（用于取身份证后四位）
        :return: 最终输出文件的完整路径
        """
        # 还原目录结构
        rel_dir = os.path.dirname(template_rel_path)
        target_dir = os.path.join(output_dir, rel_dir) if rel_dir else output_dir
        os.makedirs(target_dir, exist_ok=True)

        filename = os.path.basename(template_rel_path)
        target_path = os.path.join(target_dir, filename)

        # 应用重名策略
        strategy = self.settings.rename_strategy
        if strategy == "overwrite":
            return target_path
        elif strategy == "skip":
            if os.path.exists(target_path):
                return ""  # 返回空表示跳过
            return target_path
        else:  # append_seq
            return self._apply_append_seq(target_path, variables)

    def _apply_append_seq(self, target_path: str, variables: Dict[str, str]) -> str:
        """
        追加序号策略：若文件已存在，追加 _序号_身份证后四位。
        例如 申请表.docx -> 申请表_1_1234.docx
        """
        if not os.path.exists(target_path):
            return target_path

        id_card_var = self.settings.get("id_card_var", "身份证号")
        id_card = str(variables.get(id_card_var, "")).strip()
        id_suffix = id_card[-4:] if len(id_card) >= 4 else ""

        stem, ext = os.path.splitext(os.path.basename(target_path))
        dir_name = os.path.dirname(target_path)

        seq = 1
        while True:
            if id_suffix:
                new_name = f"{stem}_{seq}_{id_suffix}{ext}"
            else:
                new_name = f"{stem}_{seq}{ext}"
            new_path = os.path.join(dir_name, new_name)
            if not os.path.exists(new_path):
                return new_path
            seq += 1

    def get_logger(self, output_dir: str) -> logging.Logger:
        """获取操作日志 logger，日志写入输出目录"""
        if self._logger is not None:
            return self._logger

        log_filename = self.settings.get("log_filename", "operation.log")
        log_path = os.path.join(output_dir, log_filename)

        logger = logging.getLogger("doc_filler")
        logger.setLevel(logging.INFO)
        # 避免重复添加 handler
        if not logger.handlers:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(fh)
        self._logger = logger
        return logger

    def reset_logger(self) -> None:
        """重置 logger（切换输出目录时调用）"""
        if self._logger is not None:
            for h in self._logger.handlers:
                h.close()
            self._logger.handlers.clear()
            self._logger = None


def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    # Windows 文件名非法字符：\ / : * ? " < > |
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip()

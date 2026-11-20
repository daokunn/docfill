"""生成结果汇总的数据模型（纯逻辑，不依赖 UI，可独立测试）。

把一次生成（单人/多人都适用）中散落的各类结果汇总成一份报告，
供界面用"一个窗口一屏看全"地展示：
  - 顶部状态带：全绿（无失败）或有红（有失败）
  - 分区：文档生成失败 / 写入失败 / 清单追加失败(可重试) / 成功明细 / 校验问题
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ItemResult:
    """单个文档的结果。"""
    name: str
    path: str = ""
    error: str = ""
    kind: str = "ok"   # ok / generate / write


@dataclass
class GenerateReport:
    """一次生成的完整结果。"""
    success: List[ItemResult] = field(default_factory=list)
    gen_failures: List[ItemResult] = field(default_factory=list)
    write_failures: List[ItemResult] = field(default_factory=list)
    validation_issues: List[Any] = field(default_factory=list)
    ledger_error: str = ""
    ledger_unmatched: List[str] = field(default_factory=list)
    ledger_note: str = ""
    output_dir: str = ""
    people_count: int = 0

    @property
    def has_failure(self) -> bool:
        return bool(
            self.gen_failures
            or self.write_failures
            or self.ledger_error
            or self.validation_issues
            or self.ledger_unmatched
        )

    @property
    def status_text(self) -> str:
        if self.has_failure:
            return "有问题需要处理"
        if self.success:
            return "全部成功"
        return "本次没有生成任何文档"

    @property
    def status_is_ok(self) -> bool:
        return not self.has_failure and bool(self.success)

    def add_item(self, name: str, path: str = "", error: str = "", kind: str = "ok") -> None:
        item = ItemResult(name=name, path=path, error=error, kind=kind)
        if kind == "ok":
            self.success.append(item)
        elif kind == "write":
            self.write_failures.append(item)
        else:
            self.gen_failures.append(item)

    def summary_line(self) -> str:
        parts = [f"成功 {len(self.success)} 个"]
        if self.gen_failures:
            parts.append(f"生成失败 {len(self.gen_failures)} 个")
        if self.write_failures:
            parts.append(f"写入失败 {len(self.write_failures)} 个")
        if self.validation_issues:
            parts.append(f"校验问题 {len(self.validation_issues)} 项")
        if self.ledger_error:
            parts.append("清单未写入")
        return "，".join(parts)

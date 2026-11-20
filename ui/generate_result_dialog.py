"""生成结果汇总窗口：一个窗口一屏看全。

用户诉求：生成结束后不弹多个窗口，也不用底部日志翻找。
  - 顶部醒目状态带：全绿（全部成功）/ 红色（有问题）；
  - 分区明细：文档生成失败 / 写入失败 / 校验问题 / 移交清单(含重试追加) / 成功明细；
  - 有问题的分区自动展开并标红，成功的收敛为可折叠摘要。
只在结果里报告，不改变任何生成行为；"重试追加"通过回调交给调用方执行。
"""

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QFrame, QSizePolicy, QMessageBox,
)

from core.generate_report import GenerateReport
from ui.style import current_style, palette, current_theme


class GenerateResultDialog(QDialog):
    """生成结果汇总弹窗。

    :param report: 生成结果报告
    :param retry_ledger: 可选回调，点【重试追加】时调用；返回 (成功?, 新提示文本)
    :param on_open_output: 可选回调，点【打开输出目录】时调用
    """

    def __init__(self, report: GenerateReport, parent=None,
                 retry_ledger: Optional[Callable] = None,
                 on_open_output: Optional[Callable] = None,
                 extra_buttons: Optional[List[tuple]] = None):
        """:param extra_buttons: 额外按钮 [(文字, 回调)]，如单人流程的【下一单】。"""
        super().__init__(parent)
        _p = palette(current_theme())
        self.OK_BG = _p["good_bg"]
        self.OK_FG = _p["good"]
        self.BAD_BG = _p["bad_bg"]
        self.BAD_FG = _p["bad"]
        self._surface = _p["surface"]
        self._border = _p["border"]
        self._text = _p["text"]
        self._muted = _p["text_muted"]
        self._good = _p["good"]
        self._warn = _p["warn"]
        self.setStyleSheet(current_style())
        self.report = report
        self.retry_ledger = retry_ledger
        self.on_open_output = on_open_output
        self.extra_buttons = extra_buttons or []
        self.setWindowTitle("生成结果")
        self.setMinimumWidth(560)
        self.setMinimumHeight(360)
        self.resize(620, 460)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 顶部状态带：醒目、整条通栏
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setMinimumHeight(56)
        self.banner.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.banner.setContentsMargins(16, 8, 16, 8)
        outer.addWidget(self.banner)

        # 明细滚动区
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.detail_layout = QVBoxLayout(content)
        self.detail_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._render_details()

        # 底部按钮
        row = QHBoxLayout()
        row.addStretch()
        for text, callback in self.extra_buttons:
            extra = QPushButton(text)
            extra.clicked.connect(callback)
            row.addWidget(extra)
        self.btn_retry = QPushButton("重试追加")
        self.btn_retry.setObjectName("primary")
        self.btn_retry.clicked.connect(self._on_retry_ledger)
        self.btn_retry.setVisible(bool(self.report.ledger_error and self.retry_ledger))
        row.addWidget(self.btn_retry)

        btn_open = QPushButton("打开输出目录")
        btn_open.clicked.connect(self._on_open_output)
        btn_open.setEnabled(bool(self.report.output_dir))
        row.addWidget(btn_open)

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("primary")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        outer.addLayout(row)

        self._refresh_banner()

    def _refresh_banner(self) -> None:
        report = self.report
        if report.status_is_ok:
            self.banner.setText(f"  ✓  {report.status_text}　·　{report.summary_line()}")
            self.banner.setStyleSheet(
                f"background:{self.OK_BG}; color:{self.OK_FG}; "
                f"font-size:13pt; font-weight:bold; border-radius:8px;")
        else:
            self.banner.setText(f"  !  {report.status_text}　·　{report.summary_line()}")
            self.banner.setStyleSheet(
                f"background:{self.BAD_BG}; color:{self.BAD_FG}; "
                f"font-size:13pt; font-weight:bold; border-radius:8px;")

    def _section(self, title: str, color: str, lines: List[str]) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{self._surface}; border:1px solid {self._border};"
            f" border-radius:8px;}}"
        )
        box = QVBoxLayout(card)
        head = QLabel(f"<b style='color:{color};'>{title}</b>")
        box.addWidget(head)
        body = QLabel("\n".join(lines))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(f"color:{self._text};")
        box.addWidget(body)
        return card

    def _render_details(self) -> None:
        report = self.report
        # 清掉旧明细
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if report.output_dir:
            path = QLabel("输出目录：" + report.output_dir)
            path.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path.setWordWrap(True)
            path.setStyleSheet(f"color:{self._muted}; padding:4px;")
            self.detail_layout.addWidget(path)

        if report.gen_failures:
            lines = [f"{i.name}：{i.error}" for i in report.gen_failures]
            self.detail_layout.addWidget(self._section(
                f"一、文档生成失败（{len(lines)}）", self._bad, lines))

        if report.write_failures:
            lines = [f"{i.name}：{i.error}" for i in report.write_failures]
            self.detail_layout.addWidget(self._section(
                f"二、写入失败（{len(lines)}）", self._bad, lines))

        if report.validation_issues:
            lines = [f"{x.variable}：{x.message}" for x in report.validation_issues]
            self.detail_layout.addWidget(self._section(
                f"三、数据校验问题（{len(lines)}）", self._warn, lines))

        if report.ledger_error:
            self.detail_layout.addWidget(self._section(
                "四、移交清单追加失败", self._bad,
                [report.ledger_error, "常见原因：清单正在 Excel 里打开，关闭后可点【重试追加】。"]))
        elif report.ledger_note:
            self.detail_layout.addWidget(self._section(
                "移交清单", self._good, [report.ledger_note]))

        if report.ledger_unmatched:
            self.detail_layout.addWidget(self._section(
                "移交清单有列没填上", self._warn,
                ["、".join(report.ledger_unmatched[:10])]))

        if report.success:
            names = [i.name for i in report.success]
            shown = "、".join(names[:20])
            if len(names) > 20:
                shown += f" …… 等 {len(names)} 个"
            self.detail_layout.addWidget(self._section(
                f"成功明细（{len(names)}）", self._good, [shown]))

        if not self.detail_layout.count():
            empty = QLabel("本次没有可显示的明细。")
            empty.setStyleSheet(f"color:{self._muted}; padding:16px;")
            self.detail_layout.addWidget(empty)

    def _on_retry_ledger(self) -> None:
        if not self.retry_ledger:
            return
        try:
            ok, message = self.retry_ledger()
        except Exception as exc:
            QMessageBox.warning(self, "重试失败", str(exc))
            return
        if ok:
            self.report.ledger_error = ""
            self.report.ledger_note = message
            self.btn_retry.setVisible(False)
            self._render_details()
            self._refresh_banner()
        else:
            self.report.ledger_error = message
            self._render_details()
            self._refresh_banner()

    def _on_open_output(self) -> None:
        if self.on_open_output:
            self.on_open_output()

"""生成结果汇总模型测试。"""

from core.generate_report import GenerateReport


def test_all_success_is_ok():
    report = GenerateReport(output_dir="D:/out")
    report.add_item("申请表.docx", path="D:/out/申请表.docx")
    assert report.status_is_ok
    assert not report.has_failure
    assert report.status_text == "全部成功"
    assert "成功 1 个" in report.summary_line()


def test_gen_failure_makes_report_red():
    report = GenerateReport()
    report.add_item("坏模板.docx", error="模板解析失败", kind="generate")
    assert report.has_failure
    assert not report.status_is_ok
    assert report.status_text == "有问题需要处理"
    assert "生成失败 1 个" in report.summary_line()


def test_write_failure_separated():
    report = GenerateReport()
    report.add_item("a.docx", error="拒绝访问", kind="write")
    assert len(report.write_failures) == 1
    assert not report.gen_failures
    assert "写入失败 1 个" in report.summary_line()


def test_ledger_error_makes_red_and_retry_possible():
    report = GenerateReport()
    report.add_item("a.docx", path="x")
    report.ledger_error = "文件被 Excel 占用"
    assert report.has_failure
    assert report.ledger_error  # 供界面显示重试追加按钮

    report.ledger_error = ""  # 重试成功后清空
    report.ledger_note = "清单已追加：新增 3 人"
    assert report.status_is_ok


def test_empty_report_text():
    report = GenerateReport()
    assert report.status_text == "本次没有生成任何文档"

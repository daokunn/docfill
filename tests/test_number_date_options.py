# -*- coding: utf-8 -*-
"""手动编号语义、configure 不清号史、按变量日期格式覆盖。"""
from core.autonumber import AutoNumberBook, resolve_manual
from core.date_format import format_output_values


def test_configure_keeps_issued_history(tmp_path):
    book = AutoNumberBook("测试", storage_path=str(tmp_path / "num.json"))
    book.configure("编号", "X-001")
    assert book.consume("编号") == "X-001"
    # 改起始号不应把已经发出去的号清空
    book.configure("编号", "Y-001")
    assert book.peek("编号") == "X-002"
    assert book.data["编号"]["seed"] == "Y-001"


def test_configure_can_explicitly_reset(tmp_path):
    book = AutoNumberBook("测试", storage_path=str(tmp_path / "num.json"))
    book.configure("编号", "X-001")
    book.consume("编号")
    book.configure("编号", "Y-001", reset=True)
    assert book.peek("编号") == "Y-001"


def test_manual_number_once_mode_does_not_touch_book(tmp_path):
    book = AutoNumberBook("测试", storage_path=str(tmp_path / "num.json"))
    book.configure("编号", "X-001")
    assert resolve_manual(book, "编号", "人工号", "once") == "人工号"
    # 账本完全没动，下一个人还是从起始号开始
    assert book.peek("编号") == "X-001"
    assert book.consume("编号") == "X-001"


def test_manual_number_book_mode_changes_next(tmp_path):
    book = AutoNumberBook("测试", storage_path=str(tmp_path / "num.json"))
    book.configure("编号", "X-001")
    assert resolve_manual(book, "编号", "X-009", "book") == "X-009"
    assert book.peek("编号") == "X-010"


def test_manual_number_empty_falls_back_to_auto(tmp_path):
    book = AutoNumberBook("测试", storage_path=str(tmp_path / "num.json"))
    book.configure("编号", "X-001")
    assert resolve_manual(book, "编号", "", "once") == "X-001"
    assert book.peek("编号") == "X-002"


def test_date_format_overrides_per_variable():
    values = {
        "申请日期": "2026-01-01",
        "出生日期": "1990-02-03",
        "起止日期": "2026-01-01~2026-03-30",
    }
    result = format_output_values(
        values, "YYYY年M月D日", "至",
        overrides={"出生日期": "YYYYMMDD", "起止日期": "YYYY-MM-DD"},
    )
    assert result["申请日期"] == "2026年1月1日"
    assert result["出生日期"] == "19900203"
    assert result["起止日期"] == "2026-01-01至2026-03-30"
    # 原值不被修改，表达式/内部 ISO 值保持干净
    assert values["出生日期"] == "1990-02-03"


def test_detect_number_overwrites():
    """模板已填编号 + 开启自动编号 → 应检出将被覆盖的字段。"""
    from core.autonumber import detect_number_overwrites
    config = {"编号": "X-001", "档案号": "A-001"}
    values = {"编号": "手工填的号", "档案号": "", "姓名": "张三"}
    result = detect_number_overwrites(values, config, locked={})
    assert result == ["编号"]


def test_detect_number_overwrites_skips_locked():
    """历史锁定号沿用原值，不算覆盖。"""
    from core.autonumber import detect_number_overwrites
    config = {"编号": "X-001"}
    values = {"编号": "历史号"}
    result = detect_number_overwrites(values, config, locked={"编号": "历史号"})
    assert result == []


def test_detect_number_overwrites_skips_empty():
    from core.autonumber import detect_number_overwrites
    config = {"编号": "X-001"}
    assert detect_number_overwrites({"编号": ""}, config, locked={}) == []

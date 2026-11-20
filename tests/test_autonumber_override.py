"""自动编号“下一次直接指定”回归测试。"""

from core.autonumber import AutoNumberBook


def test_set_next_overrides_one_generation(tmp_path):
    path = str(tmp_path / "number.json")
    book = AutoNumberBook("测试", storage_path=path)
    book.configure("档案号", "X001")
    assert book.peek("档案号") == "X001"

    book.set_next("档案号", "X009")
    assert book.next_is_override("档案号")
    assert book.peek("档案号") == "X009"

    # 只用一次：生成后回到正常递增
    assert book.consume("档案号") == "X009"
    assert not book.next_is_override("档案号")
    assert book.peek("档案号") == "X010"

    # 重新读取仍保留状态
    reloaded = AutoNumberBook("测试", storage_path=path)
    assert reloaded.peek("档案号") == "X010"

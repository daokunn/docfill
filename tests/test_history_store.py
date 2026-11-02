"""历史数据存储测试。"""

import core.history_store as history_store


def test_append_dedupe_search_clear(tmp_path):
    path = tmp_path / "history.json"
    history_store.append_history(
        "申请", {"姓名": "张三", "金额": "100"}, {"档案号": "X001"},
        name="张三", id_tail="1234", storage_path=str(path))
    history_store.append_history(
        "申请", {"姓名": "李四", "金额": "200"}, {"档案号": "X002"},
        name="李四", storage_path=str(path))
    assert len(history_store.load_history("申请", str(path))) == 2
    # 完全相同的数据只更新时间
    history_store.append_history(
        "申请", {"姓名": "张三", "金额": "100"}, {"档案号": "X001"},
        name="张三", storage_path=str(path))
    assert len(history_store.load_history("申请", str(path))) == 2
    assert len(history_store.search_history("申请", "张三", str(path))) == 1
    assert len(history_store.load_history("其他", str(path))) == 0

    removed = history_store.clear_history("申请", str(path))
    assert removed == 2
    assert history_store.load_history("申请", str(path)) == []


def test_per_business_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(history_store, "MAX_PER_BUSINESS", 3)
    path = str(tmp_path / "history.json")
    for index in range(5):
        history_store.append_history(
            "申请", {"编号": str(index)}, storage_path=path)
    records = history_store.load_history("申请", path)
    assert len(records) == 3

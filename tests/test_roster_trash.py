"""名单回收站测试（TDD）：删除的行可恢复，不丢数据。"""

import json
import os
import tempfile

from core.roster import Roster, RosterRow


def _make_roster(path):
    r = Roster("测试业务", storage_path=path)
    r.columns = ["姓名", "身份证号"]
    r.rows = [
        RosterRow(values={"姓名": "张三", "身份证号": "36070019900101123X"}),
        RosterRow(values={"姓名": "李四", "身份证号": "360700199001011234"}),
        RosterRow(values={"姓名": "王五", "身份证号": ""}),
    ]
    return r


def test_delete_moves_rows_to_trash():
    with tempfile.TemporaryDirectory() as d:
        r = _make_roster(os.path.join(d, "r.json"))
        removed = r.delete_rows([1])
        assert removed == 1
        assert len(r.rows) == 2
        assert [row.values["姓名"] for row in r.rows] == ["张三", "王五"]
        assert len(r.trash) == 1
        assert r.trash[0]["row"]["values"]["姓名"] == "李四"


def test_trash_survives_save_load():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "r.json")
        r = _make_roster(path)
        r.delete_rows([0])
        r.save()

        r2 = Roster("测试业务", storage_path=path)
        r2.load()
        assert len(r2.trash) == 1
        assert r2.trash[0]["row"]["values"]["姓名"] == "张三"


def test_restore_from_trash():
    with tempfile.TemporaryDirectory() as d:
        r = _make_roster(os.path.join(d, "r.json"))
        r.delete_rows([0, 2])
        assert len(r.rows) == 1
        # 按内容定位，不依赖回收站内部顺序
        idx = next(i for i, item in enumerate(r.trash)
                   if item["row"]["values"]["姓名"] == "王五")
        ok = r.restore_from_trash(idx)
        assert ok
        assert "王五" in [row.values["姓名"] for row in r.rows]
        assert len(r.trash) == 1


def test_clear_trash():
    with tempfile.TemporaryDirectory() as d:
        r = _make_roster(os.path.join(d, "r.json"))
        r.delete_rows([1])
        r.clear_trash()
        assert r.trash == []

# -*- coding: utf-8 -*-
"""多批次名单：迁移、增删改切、批量设值。"""
import json
import os

import pytest

from core.roster import (
    Roster, STATUS_GENERATED, STATUS_READY, roster_path,
)
from core.roster_batches import (
    active_roster, batch_index_path, create_batch, delete_batch,
    list_batches, rename_batch, set_active_batch,
)


def _legacy_payload(rows=None):
    return {
        "business": "测试业务",
        "key_field": "姓名",
        "columns": ["姓名", "身份证号"],
        "rows": [
            {"values": r, "status": "ready", "generated_at": "", "output_dir": ""}
            for r in (rows or [{"姓名": "张三", "身份证号": "36070019900101123X"}])
        ],
    }


def test_migrate_legacy_roster_into_default_batch(tmp_path):
    legacy = roster_path("测试业务", storage_dir=str(tmp_path))
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    with open(legacy, "w", encoding="utf-8") as f:
        json.dump(_legacy_payload(), f, ensure_ascii=False)

    roster = active_roster("测试业务", storage_dir=str(tmp_path))

    assert roster.key_field == "姓名"
    assert [r.values.get("姓名") for r in roster.rows] == ["张三"]
    batches = list_batches("测试业务", storage_dir=str(tmp_path))
    assert len(batches) == 1
    assert batches[0]["name"] == "默认批次"
    # 旧文件保留，迁移失败也不会丢数据
    assert os.path.exists(legacy)
    assert os.path.exists(batch_index_path("测试业务", storage_dir=str(tmp_path)))


def test_create_switch_rename_delete_batches(tmp_path):
    first = active_roster("测试业务", storage_dir=str(tmp_path))
    first.ensure_columns(["姓名", "单位"])
    first.add_row({"姓名": "张三", "单位": "甲公司"})
    first.save()

    second = create_batch(
        "测试业务", "第二批", storage_dir=str(tmp_path),
        columns=["姓名", "单位"], key_field="姓名",
        incoming=[{"姓名": "李四", "单位": "乙公司"}],
    )
    assert second["name"] == "第二批"
    assert [r.values.get("姓名") for r in active_roster(
        "测试业务", storage_dir=str(tmp_path)).rows] == ["李四"]

    first_id = list_batches("测试业务", storage_dir=str(tmp_path))[0]["id"]
    assert set_active_batch("测试业务", first_id, storage_dir=str(tmp_path))
    assert [r.values.get("姓名") for r in active_roster(
        "测试业务", storage_dir=str(tmp_path)).rows] == ["张三"]

    assert rename_batch("测试业务", first_id, "第一批改名", storage_dir=str(tmp_path))
    assert list_batches("测试业务", storage_dir=str(tmp_path))[0]["name"] == "第一批改名"

    assert delete_batch("测试业务", first_id, storage_dir=str(tmp_path))
    remaining = list_batches("测试业务", storage_dir=str(tmp_path))
    assert len(remaining) == 1
    assert remaining[0]["id"] == second["id"]
    # 删掉的不是活跃批次时，活跃批次不变
    assert [r.values.get("姓名") for r in active_roster(
        "测试业务", storage_dir=str(tmp_path)).rows] == ["李四"]


def test_delete_last_batch_recreates_default(tmp_path):
    roster = active_roster("测试业务", storage_dir=str(tmp_path))
    batch_id = getattr(roster, "batch_id", "")
    assert batch_id
    assert delete_batch("测试业务", batch_id, storage_dir=str(tmp_path))
    fresh = active_roster("测试业务", storage_dir=str(tmp_path))
    assert fresh.rows == []
    assert list_batches("测试业务", storage_dir=str(tmp_path))[0]["name"] == "默认批次"


def test_bulk_set_scope_and_skip_generated(tmp_path):
    roster = Roster("测试业务", storage_path=str(tmp_path / "r.json"))
    roster.ensure_columns(["姓名", "单位", "状态列"])
    roster.add_row({"姓名": "张三"})
    roster.add_row({"姓名": "李四"})
    roster.add_row({"姓名": "王五"})
    roster.rows[1].status = STATUS_GENERATED
    roster.refresh_status(["姓名", "单位"])

    changed = roster.bulk_set([0, 1, 2], "单位", "甲公司", skip_generated=True)
    assert changed == 2
    assert roster.rows[0].values["单位"] == "甲公司"
    assert "单位" not in roster.rows[1].values
    assert roster.rows[2].values["单位"] == "甲公司"

    # 关闭跳过时已生成行也会被设置
    changed = roster.bulk_set([1], "单位", "乙公司", skip_generated=False)
    assert changed == 1
    assert roster.rows[1].values["单位"] == "乙公司"
    roster.refresh_status(["姓名", "单位"])
    assert roster.rows[0].status == STATUS_READY

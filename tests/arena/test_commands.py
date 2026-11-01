from __future__ import annotations

import pytest

from openra_arena.executor.commands import CommandError, parse_command, parse_commands, resolve_item


def test_build_defaults_and_alias_kind():
    c = parse_command({"kind": "build", "item": "POWR"})
    assert (c.kind, c.item, c.count) == ("建造", "powr", 1)


@pytest.mark.parametrize("raw,msg", [
    ({"kind": "建造"}, "缺少 item"),
    ({"kind": "建造", "item": "powr", "count": 50}, "count 超出范围"),
    ({"kind": "进攻"}, "缺少 target"),
    ({"kind": "取消"}, "缺少 task_id"),
    ({"kind": "喊话", "text": "  "}, "缺少 text"),
    ({"kind": "结盟"}, "未知指令"),
    ("建造", "指令必须是对象"),
])
def test_invalid(raw, msg):
    with pytest.raises(CommandError, match=msg):
        parse_command(raw)


def test_attack_harass_shout_cancel():
    a = parse_command({"kind": "进攻", "target": "蓝方基地", "count": "6", "unit_type": "3tnk"})
    assert (a.count, a.unit_type, a.target) == (6, "3tnk", "蓝方基地")
    assert parse_command({"kind": "骚扰", "target": "蓝方"}).count == 3
    assert parse_command({"kind": "防守", "target": "中央"}).count == 5
    s = parse_command({"kind": "喊话", "text": "x" * 300})
    assert len(s.text) == 100
    assert parse_command({"kind": "取消", "task_id": "4"}).task_id == 4
    assert parse_command({"kind": "撤退"}).task_id is None


def test_parse_many_collects_errors():
    ok, errors = parse_commands([{"kind": "建造", "item": "e1", "count": 5}, {"kind": "?"}])
    assert len(ok) == 1 and errors == ["第 2 条：未知指令 ?"]


def test_resolve_item():
    assert resolve_item("powr", ["powr", "tent"]) == "powr"
    assert resolve_item("兵营", ["powr", "tent"]) == "tent"
    assert resolve_item("兵营", ["barr"]) == "barr"
    assert resolve_item("坦克", ["e1", "2tnk"]) == "2tnk"
    assert resolve_item("飞机", ["e1"]) is None

from __future__ import annotations

from openra_arena.executor.commands import ArenaCommand
from openra_arena.executor.tasks import TaskBook, TaskStatus


def test_ids_assign_cancel_and_prune():
    book = TaskBook()
    t1 = book.add(ArenaCommand("防守", target="中央", count=5), 10)
    t2 = book.add(ArenaCommand("进攻", target="蓝方基地"), 20)
    assert (t1.id, t2.id) == (1, 2)
    book.assign(t1, [100, 101])
    book.assign(t2, [101, 102])
    assert book.owner_of(101) == 2 and t1.units == {100}
    assert book.unassigned([100, 101, 103]) == [103]
    book.release(t1, [100])
    assert t1.units == set() and book.owner_of(100) is None
    book.assign(t1, [100])
    book.prune_dead({100, 102})
    assert t2.units == {102}
    assert book.cancel(2, 30) == [102]
    assert t2.status == TaskStatus.CANCELLED and t2.finished_tick == 30
    assert book.cancel(2, 31) == [] and book.cancel(99, 31) == []
    assert [t.id for t in book.active()] == [1]


def test_finish_and_recent():
    book = TaskBook()
    tasks = [book.add(ArenaCommand("建造", item="e1", count=1), i) for i in range(8)]
    for t in tasks[:7]:
        book.finish(t, TaskStatus.DONE, "已下单", 100 + t.id)
    recent = book.recent(limit=3)
    assert [t.id for t in recent] == [8, 7, 6, 5]
    assert tasks[0].note == "已下单"

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from openra_arena.executor.commands import ArenaCommand


class TaskStatus(str, Enum):
    ACTIVE = "进行中"
    DONE = "完成"
    FAILED = "失败"
    CANCELLED = "已取消"


@dataclass
class Task:
    id: int
    command: ArenaCommand
    created_tick: int
    status: TaskStatus = TaskStatus.ACTIVE
    note: str = ""
    units: set[int] = field(default_factory=set)
    data: dict = field(default_factory=dict)
    finished_tick: int | None = None


class TaskBook:
    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next = 1
        self._owner: dict[int, int] = {}

    def add(self, command: ArenaCommand, tick: int) -> Task:
        task = Task(self._next, command, tick)
        self._tasks[task.id] = task
        self._next += 1
        return task

    def get(self, task_id: int) -> Task | None:
        return self._tasks.get(task_id)

    def active(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.ACTIVE]

    def _release(self, task: Task) -> list[int]:
        freed = sorted(task.units)
        for a in freed:
            self._owner.pop(a, None)
        task.units.clear()
        return freed

    def finish(self, task: Task, status: TaskStatus, note: str, tick: int) -> list[int]:
        task.status, task.note, task.finished_tick = status, note, tick
        return self._release(task)

    def cancel(self, task_id: int, tick: int) -> list[int]:
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.ACTIVE:
            return []
        return self.finish(task, TaskStatus.CANCELLED, "已取消", tick)

    def assign(self, task: Task, actor_ids: Iterable[int]) -> None:
        for a in actor_ids:
            prev = self._owner.get(a)
            if prev is not None and prev != task.id:
                self._tasks[prev].units.discard(a)
            self._owner[a] = task.id
            task.units.add(a)

    def owner_of(self, actor_id: int) -> int | None:
        return self._owner.get(actor_id)

    def unassigned(self, actor_ids: Iterable[int]) -> list[int]:
        return [a for a in actor_ids if a not in self._owner]

    def release(self, task: Task, actor_ids: Iterable[int]) -> None:
        for a in actor_ids:
            if self._owner.get(a) == task.id:
                del self._owner[a]
            task.units.discard(a)

    def prune_dead(self, alive: set[int]) -> None:
        for a in [a for a in self._owner if a not in alive]:
            self._tasks[self._owner.pop(a)].units.discard(a)

    def recent(self, limit: int = 5) -> list[Task]:
        done = sorted((t for t in self._tasks.values() if t.status != TaskStatus.ACTIVE),
                      key=lambda t: (t.finished_tick or 0, t.id), reverse=True)[:limit]
        active = sorted(self.active(), key=lambda t: t.id, reverse=True)
        return active + done

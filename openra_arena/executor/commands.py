from __future__ import annotations

from dataclasses import dataclass

KINDS = ("建造", "进攻", "防守", "扩张", "骚扰", "撤退", "喊话", "取消")
KIND_ALIASES = {"build": "建造", "attack": "进攻", "defend": "防守", "expand": "扩张", "harass": "骚扰",
                "retreat": "撤退", "say": "喊话", "shout": "喊话", "cancel": "取消"}
ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "电厂": ("powr",), "高级电厂": ("apwr",), "矿场": ("proc",), "兵营": ("tent", "barr"), "战车工厂": ("weap",),
    "雷达": ("dome",), "维修厂": ("fix",), "科技中心": ("atek", "stek"), "机场": ("afld",), "直升机坪": ("hpad",),
    "基地车": ("mcv",), "矿车": ("harv",), "步兵": ("e1",), "火箭兵": ("e3",), "工程师": ("e6",),
    "坦克": ("3tnk", "2tnk", "1tnk"), "重坦": ("4tnk", "3tnk"), "轻坦": ("1tnk",), "吉普": ("jeep",),
    "防空": ("sam", "agun"), "炮塔": ("gun", "ftur", "tsla", "pbox"),
}
REQUIRED = {"建造": "item", "进攻": "target", "防守": "target", "扩张": "target", "骚扰": "target",
            "喊话": "text", "取消": "task_id"}
COUNT_RULES = {"建造": (1, 20, 1), "进攻": (0, 200, 0), "防守": (1, 30, 5), "骚扰": (1, 10, 3)}
MAX_SHOUT = 100


class CommandError(ValueError):
    pass


@dataclass(frozen=True)
class ArenaCommand:
    kind: str
    item: str | None = None
    count: int = 0
    unit_type: str | None = None
    target: str | None = None
    task_id: int | None = None
    text: str | None = None


def _int(value, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise CommandError(f"{field} 必须是整数") from None


def parse_command(raw) -> ArenaCommand:
    if not isinstance(raw, dict):
        raise CommandError("指令必须是对象")
    kind = str(raw.get("kind", "")).strip()
    kind = KIND_ALIASES.get(kind.lower(), kind)
    if kind not in KINDS:
        raise CommandError(f"未知指令 {raw.get('kind', '')}")
    fields = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
    need = REQUIRED.get(kind)
    if need and fields.get(need) in (None, ""):
        raise CommandError(f"缺少 {need}")
    count = 0
    if kind in COUNT_RULES:
        lo, hi, default = COUNT_RULES[kind]
        count = default if fields.get("count") in (None, "") else _int(fields["count"], "count")
        if not lo <= count <= hi:
            raise CommandError(f"count 超出范围 {lo}..{hi}")
    task_id = None if fields.get("task_id") in (None, "") else _int(fields["task_id"], "task_id")
    item = str(fields["item"]).lower() if fields.get("item") else None
    text = str(fields["text"])[:MAX_SHOUT] if kind == "喊话" else None
    unit_type = str(fields["unit_type"]).lower() if fields.get("unit_type") else None
    target = str(fields["target"]) if fields.get("target") not in (None, "") else None
    return ArenaCommand(kind=kind, item=item, count=count, unit_type=unit_type, target=target, task_id=task_id, text=text)


def parse_commands(raw: list) -> tuple[list[ArenaCommand], list[str]]:
    ok: list[ArenaCommand] = []
    errors: list[str] = []
    for i, r in enumerate(raw if isinstance(raw, list) else [raw], start=1):
        try:
            ok.append(parse_command(r))
        except CommandError as e:
            errors.append(f"第 {i} 条：{e}")
    return ok, errors


def resolve_item(item: str, available: list[str]) -> str | None:
    if item in available:
        return item
    for candidate in ITEM_ALIASES.get(item, ()):
        if candidate in available:
            return candidate
    return None

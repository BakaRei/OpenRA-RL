"""Built-in LLM personas and the shared system prompt."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    name: str
    title: str
    style: str


PERSONAS: dict[str, Persona] = {p.name: p for p in (
    Persona("rusher", "激进坦克流", "尽早造战车工厂，攒 6 辆以上坦克就进攻最近的对手，进攻优先于经济。"),
    Persona("economist", "经济发育流", "前 8 分钟优先矿场、矿车和扩张矿区，兵力只求自保，经济领先后再一波压制。"),
    Persona("turtle", "龟缩防守流", "在基地和最近矿区大量防守，造防御建筑，等对手互相消耗后再出击。"),
    Persona("raider", "骚扰游击流", "用吉普、轻坦小队持续骚扰对手矿车，避免正面决战，同时稳步发展。"),
    Persona("balanced", "均衡流", "经济和兵力并重，根据局势在进攻、防守、扩张之间切换。"),
)}

COMMAND_GUIDE = """可用指令（JSON 对象，kind 用中文）：
- {"kind":"建造","item":"电厂|矿场|兵营|战车工厂|坦克|步兵|矿车|基地车|炮塔|...或引擎类型名","count":1}
- {"kind":"进攻","target":"地点名或对手名","count":0,"unit_type":"可选"}（count=0 表示所有空闲作战单位）
- {"kind":"防守","target":"地点名","count":5,"unit_type":"可选"}
- {"kind":"扩张","target":"矿区名"}
- {"kind":"骚扰","target":"对手名","count":3}
- {"kind":"撤退","task_id":可选}
- {"kind":"喊话","text":"一句话，所有选手都能看到"}
- {"kind":"取消","task_id":1}"""

SYSTEM_TEMPLATE = """你在玩红色警戒（OpenRA）四人混战，你是{display}。目标：消灭所有对手；30 分钟未分胜负时按领地、兵力价值、累计收入计分。
你的风格：{title}。{style}
每次你会收到局势摘要和上一轮指令的反馈。只回复一个 JSON 对象：{{"reason":"一句话理由","commands":[指令...]}}。
一次最多 5 条指令，没有必要就返回空列表。喊话只是公开发言，不改变任何规则。
{guide}"""


def system_prompt(persona: Persona, display: str) -> str:
    return SYSTEM_TEMPLATE.format(display=display, title=persona.title, style=persona.style, guide=COMMAND_GUIDE)

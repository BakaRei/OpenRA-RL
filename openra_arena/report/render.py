"""Static single-file HTML battle report (inline CSS + SVG, no JS, no network)."""

from __future__ import annotations

from html import escape
from pathlib import Path

from openra_arena.report.charts import line_chart_svg, series, territory_frames, territory_svg
from openra_arena.report.commentary import REASONS, build_facts, make_commentary
from openra_arena.report.journey import bot_journey
from openra_arena.report.loader import SLOT_COLORS, MatchData, clock, load_match
from openra_arena.report.moments import Moment, key_moments
from openra_env.config import LLMConfig

CSS = """body{font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;max-width:980px;margin:24px auto;
padding:0 16px;color:#222;background:#f6f4ef;line-height:1.5}h1{margin-bottom:4px}h2{margin-top:28px;
border-bottom:1px solid #e4e0d8;padding-bottom:4px}table{border-collapse:collapse;background:#fff;width:100%}
td,th{border:1px solid #ddd;padding:4px 10px;text-align:left}th{background:#f3efe6}
.frames{display:flex;flex-wrap:wrap;gap:8px}.moment{margin:4px 0;background:#fff;padding:6px 10px}
.tag{display:inline-block;min-width:52px;color:#666;font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:4px}
.journey li{margin-bottom:6px}.muted{color:#888;font-size:13px}
.warn{background:#fdecea;border:1px solid #d9363e;padding:6px 10px}.chart{background:#fff;margin:8px 0}"""

MOMENT_ICON = {
    "first_contact": "⚔", "big_battle": "💥", "base_destroyed": "🏚", "building_lost": "🏚",
    "player_lost": "☠", "shout": "📣", "takeover": "🤖", "fallback": "🤖",
}

DRIVERS = {"external": "外部 bot", "builtin": "内置 AI"}


def _dot(player: str) -> str:
    return f'<span class="dot" style="background:{SLOT_COLORS.get(player, "#333")}"></span>'


def _commands_text(cmds: list) -> str:
    parts = []
    for c in cmds or []:
        if isinstance(c, dict):
            parts.append(" ".join(str(c[k]) for k in ("kind", "item", "target", "count", "text") if c.get(k)))
    return "；".join(parts) or "（无指令）"


def _driver_text(slot: dict) -> str:
    driver = slot.get("driver", "")
    if driver == "persona":
        return f"角色 {slot.get('persona', '')}"
    return DRIVERS.get(driver, driver)


def render_html(data: MatchData, moments: list[Moment], journey: dict[str, list[dict]], commentary: list[str],
                commentary_source: str) -> str:
    meta = data.meta
    e = escape
    winner = meta.get("winner")
    headline = f"{data.name(winner)}获胜" if winner else REASONS.get(meta.get("end_reason", ""), "对局结束")
    out = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        f"<title>战报 {e(meta.get('match_id', ''))}</title><style>{CSS}</style></head><body>",
        f"<h1>红警 Bot 竞技场战报：{e(headline)}</h1>",
        ("<p class='warn'>对局异常终止：引擎在比赛中途退出，以下数据截至最后一次采样。</p>"
         if meta.get("end_reason") == "engine_crashed" else ""),
        (f"<p class='muted'>对局 {e(meta.get('match_id', ''))} · 地图 {e(meta.get('map', ''))} · "
         f"时长 {clock(meta.get('duration_ticks', 0))} · 结束方式 {e(REASONS.get(meta.get('end_reason', ''), ''))}</p>"),
        ("<h2>排名</h2><table><tr><th>名次</th><th>选手</th><th>操控</th><th>得分</th><th>领地</th>"
         "<th>兵力价值</th><th>累计收入</th><th>状态</th></tr>"),
    ]
    drivers = {s["slot"]: s for s in meta.get("slots", [])}
    for r in meta.get("ranking", []):
        p = r["player"]
        state = "存活" if r["alive"] else f"{clock(r['eliminated_tick'] or 0)} 出局"
        out.append(
            f"<tr><td>{r['rank']}</td><td>{_dot(p)}{e(data.name(p))}</td><td>{e(_driver_text(drivers.get(p, {})))}</td>"
            f"<td>{r['score']}</td><td>{r['territory']}</td><td>{r['army_value']}</td><td>{r['earned']}</td>"
            f"<td>{e(state)}</td></tr>")
    out.append("</table>")
    if any(not s.get("observed", True) for s in drivers.values()):
        out.append("<p class='muted'>注：内置 AI 槽位没有自己的观测，领地只按其他选手看到的单位估算，兵力和收入记为 0。</p>")
    src = "大模型解说（已核对时间）" if commentary_source == "llm" else "模板解说"
    out.append(f"<h2>赛后解说</h2><p class='muted'>{src}</p>" + "".join(f"<p>{e(p)}</p>" for p in commentary))
    out.append("<h2>关键时刻</h2>")
    for m in moments:
        out.append(f"<div class='moment'><span class='tag'>{m.clock}</span>{MOMENT_ICON.get(m.kind, '•')} "
                   f"{e(m.title)}</div>")
    if not moments:
        out.append("<p>无</p>")
    out.append("<h2>走势</h2>")
    names = data.display
    for metric, title in (("army_value", "兵力价值"), ("earned", "累计收入"), ("territory", "领地数")):
        out.append(line_chart_svg(title, series(data, metric), names))
    out.append("<h2>领地变化（每 30 秒）</h2><div class='frames'>")
    out += [territory_svg(data, f) for f in territory_frames(data)]
    out.append("</div><h2>Bot 心路历程</h2>")
    for p, ds in journey.items():
        out.append(f"<h3>{_dot(p)}{e(data.name(p))}</h3><ul class='journey'>")
        for d in ds:
            out.append(f"<li><b>{clock(d['t'])}</b> {e(d.get('reason') or '（没写理由）')}<br>"
                       f"<span class='muted'>指令：{e(_commands_text(d.get('commands')))}；"
                       f"反馈：{e(d.get('feedback', ''))}</span></li>")
        if not ds:
            out.append("<li class='muted'>没有记录到决策</li>")
        out.append("</ul>")
    out.append("<h2>回放</h2><ul>")
    for r in data.replays:
        rel = r.relative_to(data.root).as_posix()
        out.append(f"<li><a href='{e(rel)}'>{e(r.name)}</a>（用 OpenRA 客户端打开）</li>")
    if not data.replays:
        out.append("<li class='muted'>没有找到录像文件</li>")
    out.append("</ul></body></html>")
    return "\n".join(out)


async def build_report(match_dir: Path, llm: LLMConfig | None = None, chat=None) -> Path:
    data = load_match(match_dir)
    moments = key_moments(data)
    facts = build_facts(data, moments)
    kwargs = {"chat": chat} if chat is not None else {}
    paragraphs, source = await make_commentary(facts, llm, **kwargs)
    html = render_html(data, moments, bot_journey(data, moments), paragraphs, source)
    path = match_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    return path

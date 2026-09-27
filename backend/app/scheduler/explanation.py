"""解释引擎 —— 把排程的决策 trace 变成「人话」。

保留项:命中谁的什么层级、为何时间/预算可行。
未入选项:引用让步审计的 notes/ledger 给出被排除的真实原因。
"""

from __future__ import annotations

from ..data.loader import pois_by_id
from ..models import Concession, DayStop, Explanation, Participant, POI
from .constraints import fmt_minute
from .tiers import LEVELS, WEIGHT

_LEVEL_LABEL = {"must": "必去", "want": "想去", "ok": "可接受"}
_DRAG_MAP = {"must": "心心念念", "want": "很期待", "ok": "不排斥"}


def _like_summary(p: Participant, poi_id: str) -> str | None:
    for level in LEVELS:
        if poi_id in getattr(p.pref, level):
            return f"{p.name} 的『{_LEVEL_LABEL[level]}』"
    return None


def explain_included(
    stop: DayStop, poi: POI, participants: list[Participant], day_index: int
) -> Explanation:
    likes = [s for s in (_like_summary(p, stop.poi_id) for p in participants) if s]
    reasons: list[str] = []
    top = ""
    if likes:
        levels = [l for l in LEVELS if any(pid == stop.poi_id for p in participants for pid in getattr(p.pref, l))]
        top = max(levels, key=lambda l: WEIGHT[l]) if levels else None
        reasons.append("命中 " + "、".join(likes[:3]))
        if top == "must":
            reasons.append("这是某位的『必去』,优先级最高,优先保障")
    travel_note = f"本程 {stop.travel_mode} {stop.travel_min} 分钟"
    if stop.travel_mode == "步行":
        travel_note += "(步行可达,不费预算)"
    reasons.append(f"{fmt_minute(stop.start_min)}—{fmt_minute(stop.end_min)} 开放时间与当日时间窗契合,{travel_note}")
    if stop.price:
        reasons.append(f"门票 ¥{stop.price:.0f},符合预算")
    return Explanation(
        poi_id=stop.poi_id, included=True,
        title=f"为什么安排 {poi.name}",
        reasons=reasons,
        who_likes=list(dict.fromkeys(s.split(" 的")[0] for s in likes)),
        level=top or "",
    )


def explain_excluded(poi: POI, participants: list[Participant],
                     notes: list[Concession], ledger: list[Concession]) -> Explanation | None:
    """本城市未被安排到的 POI,能给出解释的才产出(避免几百条噪音)。"""
    who = {"must": [], "want": [], "ok": []}
    for p in participants:
        for level in LEVELS:
            if poi.id in getattr(p.pref, level):
                who[level].append(p.name)
    if not any(who.values()):
        return None
    note = next((c for c in notes if c.loser_poi == poi.name), None)
    conceded = [c for c in ledger if c.loser_poi == poi.name]
    reasons: list[str] = []
    if note:
        reasons.append(note.reason)
    else:
        reasons.append("未纳入最终行程")
    for c in conceded:
        reasons.append(f"{c.participant_name} 因此记让步 1 次(第 {c.round} 轮)")
    top = max((l for l in who if who[l]), key=lambda l: WEIGHT[l])
    level_label = _LEVEL_LABEL[top]
    return Explanation(
        poi_id=poi.id, included=False,
        title=f"为什么没安排 {poi.name}",
        reasons=reasons,
        who_likes=who[top],
        who_conceded=[c.participant_name for c in conceded],
        level=top,
    )


def build_explanations(
    participants: list[Participant],
    stops_by_day: dict[int, list[DayStop]],
    notes: list[Concession],
    ledger: list[Concession],
    city: str,
    day_offset: int = 0,
) -> list[Explanation]:
    pois = pois_by_id(city)
    exps: list[Explanation] = []
    for day in sorted(stops_by_day):
        for stop in stops_by_day[day]:
            exps.append(explain_included(stop, pois[stop.poi_id], participants, day + day_offset))
    # 未入选里只解释有人表过态的
    used_set = {s.poi_id for stops in stops_by_day.values() for s in stops}
    requested = {pid for p in participants for l in LEVELS for pid in getattr(p.pref, l)}
    for pid in requested:
        poi = pois.get(pid)
        if poi is None or pid in used_set:
            continue
        e = explain_excluded(poi, participants, notes, ledger)
        if e:
            exps.append(e)
    return exps
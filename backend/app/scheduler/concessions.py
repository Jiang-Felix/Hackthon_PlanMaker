"""让步账本审计 —— 报告层,不是决策层。

从原 engine.py 迁出。这些函数全部只做**可行性判断**(借助 constraints.can_add),
不含任何搜索/优化,因此在移除白盒决策引擎后必须完整保留:
它们回答的是"某个未入选的诉求,当初是不是**本可以被满足**",用于产出
「谁在什么时候让步了」的公平账本(评审第 3 条的可解释落点)。
"""

from __future__ import annotations

from ..models import Concession, DayStop, Participant, POI
from .constraints import can_add


def _poi_of(stop: DayStop, pois_by_id: dict[str, POI]) -> POI | None:
    """由停留反查真实 POI(用于正确的移动距离计算)。"""
    return pois_by_id.get(stop.poi_id)


def _try_insert(
    stops: list[DayStop], i: int, poi: POI, hotel: tuple[float, float],
    remaining_budget: float, pois_by_id: dict[str, POI], headcount: int = 1,
) -> bool:
    """在 stops 序列位置 i 插入 poi,校验时间/预算可行性。

    `remaining_budget` 是「门票+交通」预算,门票按 `price × headcount` 计。
    """
    def group_stop_cost(st: DayStop) -> float:
        return st.price * max(1, headcount) + st.travel_cost

    if i == len(stops):
        prev_stop = stops[-1] if stops else None
        prev_poi = _poi_of(prev_stop, pois_by_id) if prev_stop else None
        stop, _err = can_add(poi, prev_poi, hotel, prev_stop.end_min if prev_stop else 0,
                             remaining_budget, headcount)
        return stop is not None

    # 中间插:插入点起整体顺延,逐项校验不越界
    tail = stops[i:]
    prev_stop = stops[i - 1] if i > 0 else None
    cur = prev_stop.end_min if prev_stop else 0
    prev_poi = _poi_of(prev_stop, pois_by_id) if prev_stop else None

    stop, _err = can_add(poi, prev_poi, hotel, cur, remaining_budget, headcount)
    if stop is None:
        return False
    cur = stop.end_min
    prev_poi = poi
    rem = remaining_budget - group_stop_cost(stop)

    for ts in tail:
        tp = _poi_of(ts, pois_by_id)
        if tp is None:
            return False
        s2, _ = can_add(tp, prev_poi, hotel, cur, rem, headcount)
        if s2 is None:
            return False
        cur = s2.end_min
        prev_poi = tp
        rem -= group_stop_cost(s2)
    return True


def _could_fit(
    poi: POI, stops_by_day: dict[int, list[DayStop]], days: int,
    hotel: tuple[float, float], remaining_budget: float, pois_by_id: dict[str, POI],
    headcount: int = 1,
) -> bool:
    """能否把 poi 塞进任意一天的任意插入位(纯时间+预算可行性)。"""
    for day in range(days):
        stops = stops_by_day.get(day, [])
        for i in range(len(stops) + 1):
            if _try_insert(stops, i, poi, hotel, remaining_budget, pois_by_id, headcount):
                return True
    return False


def _window_or_budget_reason(
    poi: POI, stops_by_day: dict[int, list[DayStop]], days: int,
    hotel: tuple[float, float], total_budget: float, pois_by_id: dict[str, POI],
    headcount: int = 1, essentials_total: float = 0.0,
) -> str:
    rem_budget = (total_budget - essentials_total) - sum(
        s.price * headcount + s.travel_cost for stops in stops_by_day.values() for s in stops)
    for day in range(days):
        stops = stops_by_day.get(day, [])
        prev_stop = stops[-1] if stops else None
        prev_poi = _poi_of(prev_stop, pois_by_id) if prev_stop else None
        stop, err = can_add(poi, prev_poi, hotel, prev_stop.end_min if prev_stop else 0,
                            rem_budget, headcount)
        if stop is not None:
            return "与已排行程时间冲突,单日排满"
        if err:
            return err
    return "不能在任何一天的时间/预算里安排"


def audit_concessions(
    participants: list[Participant],
    pois_by_id: dict[str, POI],
    stops_by_day: dict[int, list[DayStop]],
    days: int,
    total_budget: float,
    hotel: tuple[float, float],
    init_concessions: list[Concession] | None = None,
    *,
    headcount: int | None = None,
    essentials_total: float = 0.0,
) -> tuple[list[Concession], list[Concession]]:
    """返回 (让步账本:本可安排却未被采纳才记, 未入选原因清单:供解释用)。

    `kind` 记录**真实原因**,三类:
    - passed_over       本可安排却未被采纳 —— 唯一进账本的一类
    - out_of_capacity   时间/预算确实塞不下
    - refused_by_other  被他人明确列为『不去』

    后两类是 `round=-1` 的**解释材料**,只流向 explanations,不计入让步账本 ——
    它们不是"谁的让步",而是物理容量与他人硬约束的结果;记进账本会虚增轮换优先权。

    经济口径(评审经济计算):门票按**人数**(headcount)计、打车共享一次、
    食宿(essentials_total)先扣掉 —— 门票+交通在剩余预算里竞争。
    """
    n = headcount if headcount is not None else len(participants)
    used = {s.poi_id for stops in stops_by_day.values() for s in stops}
    ledger: list[Concession] = list(init_concessions or [])
    notes: list[Concession] = []
    # 按 (谁, 让出了什么) 去重:重排时旧账本会被重新审计一遍,不去重的话同一条
    # "让出上海天文馆"每次重排都追加一次,round 无界膨胀、时间线出现四遍同样的话。
    seen = {(c.participant_id, c.loser_poi) for c in ledger}
    round_no = len(ledger)
    spent_total = sum(s.price * n + s.travel_cost for stops in stops_by_day.values() for s in stops)
    disposable = total_budget - essentials_total

    for p in participants:
        for level in ("must", "want"):
            for pid in getattr(p.pref, level):
                if pid in used or pid not in pois_by_id:
                    continue
                poi = pois_by_id[pid]
                ref_users = [q.name for q in participants if pid in q.pref.refuse and q.id != p.id]
                if ref_users:
                    notes.append(Concession(round=-1, participant_id=p.id, participant_name=p.name,
                                            loser_poi=poi.name, kind="refused_by_other",
                                            reason=f"被 {','.join(ref_users)} 明确列为『不接受』;排除"))
                    continue
                if not _could_fit(poi, stops_by_day, days, hotel, disposable - spent_total,
                                  pois_by_id, headcount=n):
                    notes.append(Concession(round=-1, participant_id=p.id, participant_name=p.name,
                                            loser_poi=poi.name, kind="out_of_capacity",
                                            reason=_window_or_budget_reason(poi, stops_by_day, days, hotel,
                                                                            total_budget, pois_by_id,
                                                                            headcount=n,
                                                                            essentials_total=essentials_total)))
                    continue
                if (p.id, poi.name) in seen:
                    continue
                round_no += 1
                seen.add((p.id, poi.name))
                ledger.append(Concession(
                    round=round_no, participant_id=p.id, participant_name=p.name,
                    loser_poi=poi.name, kind="passed_over",
                    # 旧版这里写的是「与更高优先级安排冲突」—— 但能走到这一行,
                    # 恰恰说明 _could_fit 为真:时间预算都放得下,根本没有冲突。
                    # 真实原因是"本可安排却未被采纳",这才是该记的账。
                    reason="本可安排却未被采纳(时间与预算都放得下),已记入待补偿",
                ))
    return ledger, notes
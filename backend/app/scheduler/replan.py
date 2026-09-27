"""动态重排 —— 某位成员中途改偏好后的增量重排。

原则(选作项加分点):
1. 已执行到 current_day 之前的天数完全冻结(不改动)。
2. 让步账本从旧计划继承 —— 已经妥协的人,重排时获得更高的轮换优先权。
3. 只对剩余天数重跑 AI 编排,输出与旧计划在剩余天数的换入/换出 diff。

去白盒后:剩余段由 AI 生成,但**冻结日以硬约束形式注入上下文**(严禁改动/重复),
并由 harness._validate 预载冻结日的 used/spent,重复出现会被直接丢弃。
"""

from __future__ import annotations

from ..data.loader import pois_by_id
from ..models import (
    DayStop,
    ReplanResult,
    StructuredPref,
    TagPref,
    TripState,
)
from .assembly import build_plan
from .concessions import audit_concessions
from .cost import essentials_total, sync_essentials
from .fairness import build_fairness_report
from .harness import ai_schedule, assess_soft_rows


def replan(
    trip: TripState,
    participant_id: str | None,
    new_pref: StructuredPref,
    current_day: int,
    *,
    new_soft: TagPref | None = None,
) -> ReplanResult:
    """重排:冻结 current_day 之前的天,自 current_day 起重排剩余天。

    `participant_id=None` 时是**纯重排**:不改任何成员的偏好(偏好/规则页的改动
    已各自持久化),只冻结已过期天并重排剩余天,适用于「更新行程」。
    """
    current_day = max(0, current_day)
    sync_essentials(trip)  # auto 模式食宿单价按当前偏好刷现值
    old_plan = trip.current_plan
    city_pois = pois_by_id(trip.city)
    hotel = (trip.hotel_lat, trip.hotel_lng)

    # 轮换欠账必须在**改偏好之前**、且只按「要重排的那几天」计算:
    # - 改完偏好再算,算的是新偏好下的欠账,不是上一轮真实被欠的;
    # - 用整程会被冻结日填平 —— 某人冻结日吃得好 → 整程 deficit=0 → 在真正要重排的
    #   日子里反而拿不到优先权,恰是轮换机制要防的失效模式。
    prior_rows = None
    if old_plan is not None:
        remaining = {dp.day: dp.stops for dp in old_plan.days if dp.day >= current_day}
        prior_rows = build_fairness_report(
            participants=trip.participants,
            stops_by_day=remaining,
            concessions=[],
            valid_ids=set(city_pois),
        ).participants

    if participant_id is not None:
        for p in trip.participants:
            if p.id == participant_id:
                p.pref = new_pref
                if new_soft is not None:
                    p.soft = new_soft
                break

    # 冻结段:current_day 之前的停留原样保留
    frozen: dict[int, list[DayStop]] = {}
    old_stops: dict[int, set[str]] = {}
    if old_plan is not None:
        for day_plan in old_plan.days:
            if day_plan.day < current_day:
                frozen[day_plan.day] = day_plan.stops
            else:
                old_stops[day_plan.day] = {s.poi_id for s in day_plan.stops}

    old_ledger = list(old_plan.fairness.concessions) if old_plan else []

    # AI 重排剩余段(冻结日作为硬约束注入);失败抛 PlanValidationError
    stops, _ = ai_schedule(trip, start_day=current_day, freeze=frozen, prior_rows=prior_rows)
    soft_rows = assess_soft_rows(trip, stops, city_pois)

    ledger, notes = audit_concessions(
        trip.participants, city_pois, stops, trip.days, trip.total_budget, hotel,
        init_concessions=old_ledger,
        headcount=len(trip.participants), essentials_total=essentials_total(trip))
    new_plan = build_plan(trip, stops, ledger, notes, city_pois, engine="ai", soft_rows=soft_rows)

    # diff:仅比较剩余天数
    new_set = {s.poi_id for d in range(current_day, trip.days) for s in stops.get(d, [])}
    old_set = {pid for d in old_stops for pid in old_stops[d]}
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)

    # 受影响成员用**整数**判据(拿到几个名额 / 软偏好满足几条),不用浮点 epsilon。
    # 用 set 并集而不是只遍历 new:老成员在新计划里消失也算「受影响」,旧版会静默漏掉。
    affected: list[str] = []
    if old_plan is not None:
        def key(row) -> tuple[int, int]:
            return (row.slots_got, len(row.soft_satisfied))

        old_key = {r.participant_id: key(r) for r in old_plan.fairness.participants}
        new_key = {r.participant_id: key(r) for r in new_plan.fairness.participants}
        affected = sorted(pid for pid in set(old_key) | set(new_key)
                          if old_key.get(pid) != new_key.get(pid))

    trip.current_plan = new_plan
    return ReplanResult(plan=new_plan, added=added, removed=removed, affected=affected)
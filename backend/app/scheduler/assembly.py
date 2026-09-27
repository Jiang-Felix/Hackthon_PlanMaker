"""计划组装层 —— 把「停留 + 账本 + 原因」拼装成统一的 PlanResult。

独立成模块是为了打破循环依赖:harness(AI 编排)与 replan(动态重排)都需要组装,
但 replan 要调用 harness;若 build_plan 留在 replan 里,harness 反向导入 replan 就成环。
"""

from __future__ import annotations

from ..models import Concession, CostBreakdown, DayPlan, DayStop, PlanResult, TripState
from .constraints import fmt_minute
from .explanation import build_explanations
from .fairness import build_fairness_report


def build_plan(
    trip: TripState,
    stops_by_day: dict[int, list[DayStop]],
    ledger: list[Concession],
    notes: list[Concession],
    city_pois: dict,
    engine: str = "ai",
    soft_rows: dict | None = None,
) -> PlanResult:
    """把排程产物组装成 PlanResult(首排与重排共用)。

    `soft_rows` 是 AI 软偏好自评结果({participant_id: {satisfied, missed, violated}}),
    由 harness.assess_soft_rows 产出后传进来 —— 本模块刻意**不引 AI**,以保持可测。

    经济口径(评审经济计算):门票按每人 × N 人、打车共享一趟、食宿按 trip 配置计入。
    """
    n = max(1, len(trip.participants))
    per_food, per_lodg = trip.food_per_head, trip.lodging_per_head
    days = trip.days
    daily_essentials = (per_food + per_lodg) * n

    tickets = round(sum(s.price for stops in stops_by_day.values() for s in stops) * n, 1)
    transport = round(sum(s.travel_cost for stops in stops_by_day.values() for s in stops), 1)
    food = round(per_food * n * days, 1)
    lodging = round(per_lodg * n * days, 1)

    days_plan: list[DayPlan] = []
    for day in range(days):
        stops = stops_by_day.get(day, [])
        stop_spent = sum(s.price * n + s.travel_cost for s in stops)
        days_plan.append(DayPlan(
            day=day,
            stops=stops,
            day_spent=round(stop_spent + daily_essentials, 1),
            day_end_note=f"当日结束于 {fmt_minute(stops[-1].end_min)}" if stops else "当日暂无安排",
        ))
    # 全部用关键字实参:位置实参在这个签名下极易把 ledger 和 soft_rows 错位绑定
    fairness = build_fairness_report(
        participants=trip.participants,
        stops_by_day=stops_by_day,
        concessions=ledger,
        soft_rows=soft_rows,
        valid_ids=set(city_pois),
    )
    explanations = build_explanations(trip.participants, stops_by_day, notes, ledger, trip.city)
    return PlanResult(
        trip_name=f"{trip.city.capitalize()} {days}日行程",
        city=trip.city,
        days=days_plan,
        explanations=explanations,
        fairness=fairness,
        total_spent=round(tickets + transport + food + lodging, 1),
        total_budget=trip.total_budget,
        engine=engine,
        cost_breakdown=CostBreakdown(
            tickets=tickets, transport=transport, food=food, lodging=lodging,
            per_head_food=per_food, per_head_lodging=per_lodg,
        ),
    )
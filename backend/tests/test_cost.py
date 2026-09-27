"""经济计算(评审「经济计算是否正确」):门票×人数、打车共享、食宿自动/手动。

回归护栏:
- 门票必须按人头计(否则 N>1 预算虚高 N 倍)
- 食宿按 trip.food_per_head/lodging_per_head 计入总花费与预算竞争
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.data.loader import pois_by_id
from app.main import app
from app.models import DayStop
from app.scheduler.assembly import build_plan
from app.scheduler.constraints import can_add
from app.scheduler.cost import disposable_budget, essentials_total, estimate_essentials, sync_essentials
from tests.conftest import make_participant

HOTEL = (31.2304, 121.4737)


def _stop(pid: str, price: float, travel: float = 0.0) -> DayStop:
    return DayStop(poi_id=pid, name=pid, price=price, travel_cost=travel,
                   start_min=600, end_min=720, arrive_min=600, travel_min=0, tags=[])


def test_headcount_scales_ticket_budget(shanghai):
    """★ 门票按人数计:2 人可放迪士尼(占 1198),3 人超 1300 被拒。"""
    disney = pois_by_id("shanghai")["sh12"]  # ¥599
    stop, _ = can_add(disney, None, HOTEL, 9 * 60, 1300, headcount=2)
    assert stop is not None and stop.price == 599
    stop, err = can_add(disney, None, HOTEL, 9 * 60, 1300, headcount=3)
    assert stop is None and "预算" in err


def test_estimate_essentials_by_preference():
    """自动估计:按成员消费/住宿偏好定每人每天餐费与每晚住宿。"""
    plain = make_participant("A")
    assert estimate_essentials([plain]) == (90.0, 180.0)
    assert estimate_essentials([make_participant("B", soft={"want": ["sp_budget"]})]) == (65.0, 90.0)
    assert estimate_essentials([make_participant("C", soft={"must": ["sp_over"]})]) == (130.0, 260.0)
    f, l = estimate_essentials([make_participant("D", soft={"ok": ["lo_hostel"]})])
    assert f == 90.0 and l == 90.0


def test_sync_essentials_auto_vs_manual(shanghai, make_trip):
    """auto 模式:偏好一改就重估;手动模式:保留用户值。"""
    trip = make_trip(days=2, budget=2000, participants=[make_participant("A")])
    trip.budget_mode = "auto"   # make_trip 默认 manual(经济中性),这里显式开 auto
    trip.participants.append(make_participant("B", soft={"must": ["sp_budget"]}))
    sync_essentials(trip)
    assert (trip.food_per_head, trip.lodging_per_head) == (65.0, 90.0)
    assert essentials_total(trip) == (65 + 90) * 2 * 2
    assert disposable_budget(trip) == 2000 - essentials_total(trip)

    trip.budget_mode = "manual"
    trip.food_per_head, trip.lodging_per_head = 120.0, 300.0
    trip.participants.append(make_participant("C", soft={"must": ["sp_over"]}))
    sync_essentials(trip)  # manual → 不被偏好覆盖
    assert (trip.food_per_head, trip.lodging_per_head) == (120.0, 300.0)


def test_build_plan_costs_and_breakdown(shanghai, make_trip):
    """总花费 = 门票×N + 打车 + 食宿;分项正确;day_spent 加总 = total_spent。"""
    trip = make_trip(days=2, budget=5000, participants=[make_participant("A", must=["sh02"]),
                                                        make_participant("B")])
    trip.budget_mode = "manual"
    trip.food_per_head, trip.lodging_per_head = 100.0, 150.0
    stops = {0: [_stop("sh02", 30.0, travel=10)], 1: [_stop("sh05", 0.0)]}
    plan = build_plan(trip, stops, [], [], pois_by_id("shanghai"))

    assert plan.cost_breakdown.tickets == 60.0          # 30 × 2 人
    assert plan.cost_breakdown.transport == 10.0        # 打车共享一趟
    assert plan.cost_breakdown.food == 400.0            # 100 × 2 × 2 天
    assert plan.cost_breakdown.lodging == 600.0         # 150 × 2 × 2 天
    assert plan.total_spent == 60 + 10 + 400 + 600
    assert plan.days[0].day_spent == (30 * 2 + 10) + (100 + 150) * 2
    assert plan.days[1].day_spent == (0) + (100 + 150) * 2
    assert sum(d.day_spent for d in plan.days) == plan.total_spent


def test_validate_respects_disposable_budget(shanghai, make_trip):
    """食宿先扣,门票+交通只能在剩余可用预算里放(时间要留够,让预算成为唯一约束)。"""
    from app.scheduler.harness import _validate

    alice = make_participant("A")
    trip = make_trip(days=1, budget=1000, participants=[alice])
    trip.budget_mode = "manual"
    trip.food_per_head, trip.lodging_per_head = 400.0, 0.0   # 食宿 400 → 门票+交通可用 600
    pois = pois_by_id("shanghai")

    blocking, trimmed, _ = _validate(trip, pois, {0: ["sh09"]})   # 东方明珠 ¥220 ≤ 600
    assert blocking == [] and trimmed == []
    # 迪士尼 ¥599 + 车费 > 600 —— 当天时间充裕,唯一被拒原因就是预算
    blocking, trimmed, _ = _validate(trip, pois, {0: ["sh12"]})
    assert any("预算" in i for i in trimmed)


def test_validate_reports_when_essentials_exceed_budget(shanghai, make_trip):
    """★ 回归护栏:食宿已吃光总预算时,给**一句可操作的说明**,
    而不是一串「会超出剩余预算(车费 ¥0)」这种让人摸不着头脑的级联报错。
    """
    from app.scheduler.harness import _validate

    alice = make_participant("A", must=["sh02"])
    trip = make_trip(days=2, budget=500, participants=[alice])
    trip.budget_mode = "manual"
    trip.food_per_head, trip.lodging_per_head = 200.0, 200.0   # 食宿 800 > 预算 500
    blocking, trimmed, _ = _validate(trip, pois_by_id("shanghai"), {0: ["sh02"]})

    assert len(blocking) == 1 and trimmed == []
    assert "食宿" in blocking[0] and "还不够覆盖" in blocking[0]


def test_settings_budget_patch_and_auto_reestimate():
    """API:auto 加偏好成员 → 默认按偏好重估;切 manual 填值 → 保留。"""
    c = TestClient(app)
    t = c.post("/api/trip", json={"city": "shanghai", "days": 2, "total_budget": 2000}).json()
    tid = t["id"]
    c.post(f"/api/trip/{tid}/participants", json={
        "name": "省省", "already_parsed": True, "structured": {"must": ["sh02"]},
        "soft": {"must": ["sp_budget"]}})
    trip = c.get(f"/api/trip/{tid}").json()
    assert trip["budget_mode"] == "auto"
    assert (trip["food_per_head"], trip["lodging_per_head"]) == (65.0, 90.0)

    c.patch(f"/api/trip/{tid}/settings",
            json={"budget": {"mode": "manual", "food_per_head": 120, "lodging_per_head": 300}})
    trip = c.get(f"/api/trip/{tid}").json()
    assert trip["budget_mode"] == "manual"
    assert (trip["food_per_head"], trip["lodging_per_head"]) == (120.0, 300.0)
"""动态重排测试:冻结已执行天、账本继承、diff 上报(走 AI 编排链路)。"""

from __future__ import annotations

from app.data.loader import pois_by_id
from app.models import StructuredPref
from app.scheduler.concessions import audit_concessions
from app.scheduler.harness import ai_plan
from app.scheduler.replan import replan
from tests.conftest import make_participant
from tests.fakes import FakeProvider, draft, patch_provider


def _ids(plan):
    return {d.day: [s.poi_id for s in d.stops] for d in plan.days}


def test_frozen_days_preserved(shanghai, make_trip, monkeypatch):
    alice = make_participant("A", must=["sh02"])
    bob = make_participant("B", must=["sh12"])
    trip = make_trip(days=2, budget=1500, participants=[alice, bob])

    patch_provider(monkeypatch, FakeProvider(draft(["sh12"], ["sh02"])))
    old_plan = ai_plan(trip)
    trip.current_plan = old_plan
    day0_before = _ids(old_plan)[0]
    assert day0_before == ["sh12"]

    # 重排:剩余天换成「天文馆 + 南京路」;冻结的 day0(迪士尼)必须原样保留
    patch_provider(monkeypatch, FakeProvider(draft([], ["sh02", "sh05"])))
    result = replan(trip, bob.id, StructuredPref(must=["sh12"]), current_day=1)

    assert _ids(result.plan)[0] == day0_before
    assert _ids(result.plan)[1] == ["sh02", "sh05"]


def test_diff_reports_changes(shanghai, make_trip, monkeypatch):
    alice = make_participant("A", must=["sh02"])
    bob = make_participant("B", must=["sh12"])
    trip = make_trip(days=2, budget=1500, participants=[alice, bob])

    patch_provider(monkeypatch, FakeProvider(draft(["sh12"], ["sh02", "sh05"])))
    trip.current_plan = ai_plan(trip)

    patch_provider(monkeypatch, FakeProvider(draft([], ["sh02", "sh21"])))
    result = replan(trip, bob.id, StructuredPref(must=["sh12"]), current_day=1)

    assert "sh21" in result.added
    assert "sh05" in result.removed


def test_ledger_inherited_without_duplication(shanghai, make_trip):
    """账本继承:**不重复**记录同一条让步(评审第 3 条「轮换优先权」的数据基础)。

    ★ 回归护栏:旧实现每次重排都把旧账本重新审计一遍再追加 —— 3 次重排后同一条
    "让出上海天文馆"会出现 4 次、round 无界膨胀。旧测试断言的正是那个重复行为。
    """
    alice = make_participant("A", must=["sh02"])
    trip = make_trip(days=1, budget=300, participants=[alice])
    pois = pois_by_id("shanghai")
    hotel = (trip.hotel_lat, trip.hotel_lng)

    # 造一份「只排了 sh05、漏掉必去 sh02」的停留 → sh02 属于"本可安排却未被采纳"
    from app.scheduler.constraints import can_add
    stop, _ = can_add(pois["sh05"], None, hotel, 9 * 60, trip.total_budget)
    stops = {0: [stop]}

    ledger1, _ = audit_concessions([alice], pois, stops, 1, trip.total_budget, hotel)
    assert len(ledger1) == 1 and ledger1[0].loser_poi == pois["sh02"].name

    # 再审计一遍(模拟重排):同一条让步不该被追加第二次
    ledger2, _ = audit_concessions([alice], pois, stops, 1, trip.total_budget, hotel,
                                   init_concessions=ledger1)
    assert len(ledger2) == 1
    assert ledger2[0].loser_poi == ledger1[0].loser_poi
    assert ledger2[0].round == 1


def test_concession_kind_and_reason_are_truthful(shanghai, make_trip):
    """★ 回归护栏:旧版把「本可安排却未被采纳」写成"与更高优先级安排冲突" —— 是假话。

    能进账本就说明 `_could_fit` 为真:时间与预算都放得下,**根本没有冲突**。
    真实原因是"本可安排却未被采纳",这才是该记的账。
    """
    alice = make_participant("A", must=["sh02"], refuse=["sh12"])
    bob = make_participant("B", want=["sh12"])
    trip = make_trip(days=1, budget=300, participants=[alice, bob])
    pois = pois_by_id("shanghai")
    hotel = (trip.hotel_lat, trip.hotel_lng)

    # 只排了免费又短的南京路 → 天文馆(sh02)本可安排却未被采纳
    from app.scheduler.constraints import can_add
    stop, _ = can_add(pois["sh05"], None, hotel, 9 * 60, trip.total_budget)
    stops = {0: [stop]}

    ledger, notes = audit_concessions([alice, bob], pois, stops, 1, trip.total_budget, hotel)

    assert [c.loser_poi for c in ledger] == [pois["sh02"].name]
    assert ledger[0].kind == "passed_over"
    # 账本里不该再出现"冲突"这种没有证据的措辞
    assert "冲突" not in ledger[0].reason
    assert "本可安排却未被采纳" in ledger[0].reason

    # 被别人 refuse 掉的诉求是**解释材料**,不进账本(否则虚增轮换优先权)
    refused = [c for c in notes if c.loser_poi == pois["sh12"].name]
    assert refused and refused[0].kind == "refused_by_other"
    # refuse 判定先于容量判定:迪士尼 ¥599 远超 ¥300 预算,但真实原因是"有人不接受",
    # 报成"预算不够"会误导(钱够也不该去)。
    assert all(c.kind != "out_of_capacity" for c in notes if c.loser_poi == pois["sh12"].name)


def test_replan_raises_when_ai_cannot_fix(shanghai, make_trip, monkeypatch):
    """重排失败同样抛错,不写 current_plan。"""
    import pytest

    from app.errors import PlanValidationError

    alice = make_participant("A", must=["sh02"])
    trip = make_trip(days=2, participants=[alice])
    # 初始计划:day0 放非必去项,必去 sh02 在 day1 → 冻结 day0 后必须重新安排 sh02
    patch_provider(monkeypatch, FakeProvider(draft(["sh05"], ["sh02"])))
    plan = ai_plan(trip)
    trip.current_plan = plan

    # 重排时 AI 给出空的剩余天 → sh02 缺失 → 三轮后抛错
    patch_provider(monkeypatch, FakeProvider(draft([], []), draft([], []), draft([], [])))
    with pytest.raises(PlanValidationError):
        replan(trip, alice.id, StructuredPref(must=["sh02"]), current_day=1)
    assert trip.current_plan is plan          # 失败不改动已有计划


def test_replan_pure_recompute_without_participant(shanghai, make_trip, monkeypatch):
    """★ 纯重排(已开始状态的「更新行程」):不指定成员、不改任何偏好。

    冻结已过期天原样保留,剩余天按**现有**偏好重排 —— 偏好/规则页的改动已各自
    持久化,这里只负责「冻结 + 重排剩余天」。
    """
    alice = make_participant("A", must=["sh02"])
    bob = make_participant("B", must=["sh12"])
    trip = make_trip(days=2, budget=1500, participants=[alice, bob])

    patch_provider(monkeypatch, FakeProvider(draft(["sh12"], ["sh02"])))
    old_plan = ai_plan(trip)
    trip.current_plan = old_plan
    day0_before = _ids(old_plan)[0]

    patch_provider(monkeypatch, FakeProvider(draft([], ["sh02", "sh05", "sh21"])))
    result = replan(trip, None, StructuredPref(), current_day=1)

    assert _ids(result.plan)[0] == day0_before          # 冻结日原样
    assert _ids(result.plan)[1] == ["sh02", "sh05", "sh21"]
    # 没改任何成员偏好
    assert alice.pref.must == ["sh02"] and bob.pref.must == ["sh12"]


def test_current_day_derived_from_wall_clock(shanghai, make_trip):
    """按墙上时钟自动算「已进行到第几天」—— 已开始后冻结的依据。

    未开始 → 0(没有任何天被冻结);跨过整 24h 才 +1;clamp 到最后一天。
    """
    from datetime import datetime

    from app.main import _current_day_for

    alice = make_participant("A")
    trip = make_trip(days=3, participants=[alice])
    now = datetime(2026, 9, 27, 14, 0)   # 固定"当前时间",测试确定性

    trip.start_at = None
    assert _current_day_for(trip, now) == 0            # 旧数据:永不自动冻结

    trip.start_at = "2026-09-28T09:00"                 # 未来出发 → 未开始
    assert _current_day_for(trip, now) == 0

    trip.start_at = "2026-09-27T09:00"                 # 今天 09:00 出发,不足 24h
    assert _current_day_for(trip, now) == 0            # 还在第 1 天

    trip.start_at = "2026-09-26T09:00"                 # 昨天出发 → 已过去 1 整天
    assert _current_day_for(trip, now) == 1            # 前 1 天冻结,今天第 2 天

    trip.start_at = "2026-09-20T09:00"                 # 出发太久 → clamp 到最后一天
    assert _current_day_for(trip, now) == 2            # days-1


def test_replan_endpoint_empty_body_updates_with_freeze(shanghai, monkeypatch):
    """★ API 集成:已开始状态点「更新行程」→ 传空 body,后端按 start_at 自动冻结。

    这是前端 SettingsView 实际发起的调用:`api.replan(trip.id, {})`。
    """
    import json
    from datetime import datetime, timedelta

    from fastapi.testclient import TestClient

    from app.ai import deepseek_provider as ds
    from app.ai.provider import reset_provider
    from app.main import app

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    reset_provider()

    # 30h 前出发 → current_day 自动算成 1(已冻结第 0 天)
    start_at = (datetime.now() - timedelta(hours=30)).isoformat(timespec="minutes")

    def fake(self, messages, temperature=0.2, timeout=None):
        text = " ".join(m.get("content", "") for m in messages)
        if "软偏好达成度" in text:
            return json.dumps({"0": {"satisfied": [], "missed": [], "violated": []}})
        return json.dumps({"days": [{"day": 0, "stops": ["sh12"]}, {"day": 1, "stops": ["sh02"]}]})

    monkeypatch.setattr(ds.DeepSeekProvider, "_chat", fake)

    try:
        c = TestClient(app)
        tid = c.post("/api/trip", json={"city": "shanghai", "days": 2,
                                        "total_budget": 1500, "start_at": start_at}).json()["id"]
        c.post(f"/api/trip/{tid}/participants", json={
            "name": "球球", "already_parsed": True,
            "structured": {"must": ["sh02"], "want": [], "refuse": [], "ok": []}})

        r = c.post(f"/api/trip/{tid}/plan")
        assert r.status_code == 200, r.text

        # 「更新行程」:空 body(不指定成员、不指定 current_day)
        r = c.post(f"/api/trip/{tid}/replan", json={})
        assert r.status_code == 200, r.text
        res = r.json()
        # 第 0 天被冻结,原样保留(迪士尼);第 1 天重排(球球的必去 sh02)
        assert [s["poi_id"] for s in res["plan"]["days"][0]["stops"]] == ["sh12"]
        assert any(s["poi_id"] == "sh02" for s in res["plan"]["days"][1]["stops"])
    finally:
        reset_provider()
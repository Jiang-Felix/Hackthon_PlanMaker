"""AI-harness 测试:上下文注入、守门校验、无兜底报错、修复轮次。"""

from __future__ import annotations

import pytest

from app.data.loader import pois_by_id, vocab_tags
from app.errors import PlanValidationError, ProviderError
from app.models import RecoSettings, TagPref
from app.scheduler.harness import _parse_draft, _validate, ai_plan, ai_schedule, build_context
from tests.conftest import make_participant
from tests.fakes import FakeProvider, draft, patch_provider


# ---------------------------------------------------------------- 草案解析
def test_draft_parsing():
    assert _parse_draft(draft(["sh02", "sh05"], ["sh12"])) == {0: ["sh02", "sh05"], 1: ["sh12"]}
    assert _parse_draft("这不是 JSON") == {}
    assert _parse_draft("```json\n{\"days\":[]}\n```") == {}  # 带代码块 → 不可用


# ---------------------------------------------------------------- 守门校验
def test_validate_catches_violations(shanghai, make_trip):
    """阻塞 vs 可裁的严重程度区分。"""
    alice = make_participant("A", must=["sh02"], refuse=["sh12"])
    trip = make_trip(participants=[alice])
    pois = pois_by_id("shanghai")

    blocking, trimmed, _ = _validate(trip, pois, {0: ["sh02"]})
    assert blocking == [] and trimmed == []            # 合法草案

    blocking, trimmed, _ = _validate(trip, pois, {0: ["nope"]})
    assert any("不认识的景点" in i for i in trimmed)   # 编造的 id → 剔除
    assert any("任何景点" in i for i in blocking)      # 全被剔 → 空方案视为阻塞

    blocking, trimmed, _ = _validate(trip, pois, {0: ["sh05", "sh12"]})
    assert any("不去" in i for i in trimmed)           # 被拒项 → 剔除
    assert any("必去" in i for i in blocking)          # 必去缺失 → 阻塞


def test_validate_must_that_cannot_fit_is_blocking(shanghai, make_trip):
    """必去项排不下 → 阻塞(不能悄悄丢掉别人的必去);非必去排不下 → 可裁。"""
    alice = make_participant("A", must=["sh18"], ok=["sh02"])  # 都 16:00 前关门
    trip = make_trip(days=1, participants=[alice])
    pois = pois_by_id("shanghai")
    # 迪士尼占满 9:00-17:00,之后两个 16:00 关门的都排不进去
    blocking, trimmed, _ = _validate(trip, pois, {0: ["sh12", "sh18", "sh02"]})
    assert any("邮政" in i for i in blocking)     # 必去被挡 → 阻塞
    assert any("天文馆" in i for i in trimmed)    # 非必去被挡 → 可裁


def test_validate_respects_freeze(shanghai, make_trip):
    """冻结日:已执行的 POI 不可重复出现;剩余段从 start_day 起校验。"""
    from app.scheduler.constraints import can_add

    alice = make_participant("A", must=["sh02"])
    trip = make_trip(days=2, participants=[alice])
    pois = pois_by_id("shanghai")
    hotel = (trip.hotel_lat, trip.hotel_lng)
    stop, _ = can_add(pois["sh12"], None, hotel, 9 * 60, trip.total_budget)
    freeze = {0: [stop]}

    blocking, trimmed, stops = _validate(trip, pois, {0: ["sh12"], 1: ["sh02"]}, start_day=1, freeze=freeze)
    assert blocking == [] and trimmed == []            # 冻结日重复出现被静默丢弃,不报错
    assert [s.poi_id for s in stops[0]] == ["sh12"]   # 冻结段原样保留
    assert [s.poi_id for s in stops[1]] == ["sh02"]


def test_validate_budget_accumulates_across_freeze(shanghai, make_trip):
    """冻结段的已花预算要从总预算里扣掉,剩余段不得超支。"""
    from app.scheduler.constraints import can_add

    alice = make_participant("A", must=[])
    trip = make_trip(days=2, budget=700, participants=[alice])
    pois = pois_by_id("shanghai")
    hotel = (trip.hotel_lat, trip.hotel_lng)
    disney, _ = can_add(pois["sh12"], None, hotel, 9 * 60, 700)  # ¥599
    freeze = {0: [disney]}
    blocking, trimmed, _ = _validate(trip, pois, {1: ["sh13"]}, start_day=1, freeze=freeze)  # 海昌 ¥399
    assert any("预算" in i for i in blocking + trimmed)


# ---------------------------------------------------------------- 上下文注入
def test_context_includes_soft_prefs_and_settings(shanghai, make_trip):
    alice = make_participant("A", must=["sh02"])
    alice.soft = TagPref(must=["en_light"], refuse=["di_spicy"])
    trip = make_trip(participants=[alice])
    trip.settings = RecoSettings(conflict_strategy="split", schedule_align="left",
                                 activity_priorities=["avoid_similar"], buffer_min=20)
    ctx = build_context(trip, pois_by_id("shanghai"))

    assert "轻松为主" in ctx or "en_light" in ctx        # 软偏好标签(中文名注入)
    assert "分量" not in ctx
    assert "分组出游" in ctx                              # 设置的中文标签
    assert "左对齐" in ctx
    assert "避免雷同" in ctx
    assert "留白=20分钟" in ctx
    # 评审三条原则必须在决策宪法里
    assert "防平均主义" in ctx and "轮换" in ctx and "平衡≠平均" in ctx


def test_context_includes_freeze_and_rotation(shanghai, make_trip):
    """轮换优先权现在按**欠账(deficit)**注入,而不是累计让步次数。

    旧版用累计次数 → 只增不减,谁先让一次就永久受照顾。改用 deficit 后自带闭环:
    补偿到位 deficit 归零,优先权自动消失。
    """
    from app.models import FairnessRow

    alice = make_participant("A", must=["sh02"])
    trip = make_trip(days=2, participants=[alice])
    prior = [FairnessRow(participant_id="x", name="小明",
                         slots_got=1, slots_owed=3.0, deficit=2)]
    ctx = build_context(trip, pois_by_id("shanghai"), start_day=1, freeze={}, prior_rows=prior)
    assert "【轮换优先权】" in ctx and "小明上轮少安排 2 个" in ctx


def test_rotation_omitted_when_nobody_is_owed(shanghai, make_trip):
    """没人被欠名额时,不输出轮换行(旧版只要有人让过步就一直输出)。

    注意「轮换」二字永远出现在决策宪法第 3 条里,所以只能断言行首标记
    `【轮换优先权】` —— 断言裸的"轮换优先权"会恒为真。
    """
    from app.models import FairnessRow

    alice = make_participant("A", must=["sh02"])
    trip = make_trip(days=2, participants=[alice])
    prior = [FairnessRow(participant_id="x", name="小明",
                         slots_got=2, slots_owed=2.0, deficit=0)]
    ctx = build_context(trip, pois_by_id("shanghai"), start_day=1, freeze={}, prior_rows=prior)
    assert "【轮换优先权】" not in ctx and "上轮少安排" not in ctx


# ---------------------------------------------------------------- 编排(无兜底)
def test_ai_plan_satisfies_invariants(shanghai, make_trip, monkeypatch):
    alice = make_participant("A", must=["sh02"], refuse=["sh12"])
    bob = make_participant("B", must=["sh07"])
    trip = make_trip(days=2, budget=1200, participants=[alice, bob])
    fake = FakeProvider(draft(["sh02", "sh05"], ["sh07", "sh06"]))
    patch_provider(monkeypatch, fake)

    plan = ai_plan(trip)
    included = {s.poi_id for d in plan.days for s in d.stops}
    assert plan.engine == "ai"
    assert {"sh02", "sh07"} <= included          # 两人必去全覆盖
    assert "sh12" not in included                # refuse 不出现
    assert plan.total_spent <= plan.total_budget


def test_ai_plan_uses_context_from_trip(shanghai, make_trip, monkeypatch):
    alice = make_participant("A", must=["sh02"])
    trip = make_trip(participants=[alice])
    fake = FakeProvider(draft(["sh02"]))
    patch_provider(monkeypatch, fake)
    ai_plan(trip)
    assert "【决策宪法" in fake.last_context
    assert "上海天文馆" in fake.last_context


def test_ai_schedule_revises_then_succeeds(shanghai, make_trip, monkeypatch):
    """首稿丢必去 → 回喂修正 → 第二稿合格。"""
    alice = make_participant("A", must=["sh02"])
    trip = make_trip(participants=[alice])
    fake = FakeProvider(draft(["sh05"]), draft(["sh02"]))
    patch_provider(monkeypatch, fake)

    stops, _ = ai_schedule(trip)
    assert [s.poi_id for s in stops[0]] == ["sh02"]
    assert fake.revise_calls and "必去" in fake.revise_calls[0]


def test_ai_schedule_raises_when_unfixable(shanghai, make_trip, monkeypatch):
    """修复轮次用尽仍不达标 → 抛 PlanValidationError(不再有确定性兜底)。"""
    alice = make_participant("A", must=["sh02"])
    trip = make_trip(participants=[alice])
    fake = FakeProvider(draft(["sh05"]), draft(["sh05"]), draft(["sh05"]))
    patch_provider(monkeypatch, fake)

    with pytest.raises(PlanValidationError) as ei:
        ai_schedule(trip)
    assert any("必去" in i for i in ei.value.issues)
    assert ei.value.attempts == 3


def test_ai_plan_raises_without_participants(make_trip):
    trip = make_trip(participants=[])
    with pytest.raises(PlanValidationError):
        ai_plan(trip)


def test_mock_provider_cannot_plan(shanghai, make_trip):
    """mock 不再具备排程能力(白盒已移除),必须显式报错而非静默返回空。"""
    from app.ai.mock_provider import MockProvider

    trip = make_trip(participants=[make_participant("A", must=["sh02"])])
    with pytest.raises(ProviderError):
        MockProvider().draft_itinerary(trip, pois_by_id("shanghai"), "ctx")

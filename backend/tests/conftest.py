"""共享测试夹具:快速构造成员与行程(显式层级偏好,不经 NL 解析,保证确定性)。"""

from __future__ import annotations

import uuid

import pytest

from app.data.loader import load_city
from app.models import Participant, StructuredPref, TagPref, TripState


@pytest.fixture(autouse=True)
def _no_live_weather(monkeypatch):
    """测试一律**不打真实天气 API**:离线可跑、结果确定、不拖慢。

    天气是增强项,取不到就降级为空 —— 排程逻辑本就该在"没有天气"下照常工作,
    所以整体替换成空是最贴近真实失败路径的桩。要测天气注入的用例自己给 build_context 传 weather。
    """
    monkeypatch.setattr("app.scheduler.harness.fetch_weather_for_trip", lambda trip: [], raising=False)


def make_participant(name: str, soft: dict | None = None, **tiers) -> Participant:
    """`soft` 是扩展软偏好(词表 tag id),与 POI 意愿分开传,避免 id 空间混淆。"""
    soft = soft or {}
    return Participant(
        id=uuid.uuid4().hex[:6],
        name=name,
        pref=StructuredPref(refuse=tiers.get("refuse", []),
                            must=tiers.get("must", []),
                            want=tiers.get("want", []),
                            ok=tiers.get("ok", [])),
        soft=TagPref(refuse=soft.get("refuse", []),
                     must=soft.get("must", []),
                     want=soft.get("want", []),
                     ok=soft.get("ok", [])),
    )


@pytest.fixture
def shanghai():
    return load_city("shanghai")


@pytest.fixture
def hangzhou():
    return load_city("hangzhou")


@pytest.fixture
def chengdu():
    return load_city("chengdu")


@pytest.fixture
def make_trip():
    def _make(city="shanghai", days=2, budget=1200.0, participants=()):
        pois = load_city(city)
        lat = sum(p.lat for p in pois) / len(pois)
        lng = sum(p.lng for p in pois) / len(pois)
        return TripState(
            id=uuid.uuid4().hex[:8],
            city=city,
            days=days,
            total_budget=budget,
            hotel_lat=lat,
            hotel_lng=lng,
            # 经济口径(评审:门票×人数/食宿)单独在 test_cost.py 里测 ——
            # 这里的排程/公平测试用「食宿为 0」保持纯逻辑可预测。
            budget_mode="manual",
            food_per_head=0.0,
            lodging_per_head=0.0,
            participants=list(participants),
        )
    return _make
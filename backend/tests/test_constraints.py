"""约束测试:预算上限、时间窗、开放时间(纯物理函数)。"""

from __future__ import annotations

from app.data.loader import pois_by_id
from app.scheduler.constraints import can_add, haversine_km, parse_open
from app.scheduler.harness import _validate
from tests.conftest import make_participant

HOTEL = (31.20, 121.47)


def test_haversine_sanity():
    d = haversine_km(31.23, 121.47, 31.24, 121.47)  # 约 1.1km 纬差
    assert 0.5 < d < 2.0


def test_parse_open():
    assert parse_open("09:00-17:00") == (540, 1020)
    assert parse_open("00:00-23:59") == (0, 1439)


def test_budget_cap_rejects(shanghai):
    expensive = next(p for p in shanghai if p.id == "sh12")  # 迪士尼 ¥599
    stop, err = can_add(expensive, None, HOTEL, 9 * 60, remaining_budget=100)
    assert stop is None
    assert "预算" in err


def test_late_arrival_rejected_by_window(shanghai):
    early_close = next(p for p in shanghai if p.id == "sh18")  # 邮政博物馆 16:00 关
    stop, err = can_add(early_close, None, HOTEL, 20 * 60, remaining_budget=2000)
    assert stop is None
    assert "关闭" in err or "开放" in err


def test_refuse_never_scheduled(shanghai, make_trip):
    """refuse 由守门校验拦截:AI 草案里出现被拒地点 → 报错且不入线。"""
    alice = make_participant("A", must=["sh02"], refuse=["sh12"])
    trip = make_trip(days=2, budget=2000, participants=[alice])
    pois = pois_by_id("shanghai")
    blocking, trimmed, stops = _validate(trip, pois, {0: ["sh12"], 1: ["sh02"]})
    assert any("不去" in i for i in trimmed)     # 被拒项被剔除(可裁)
    assert blocking == []                        # 必去 sh02 仍在 → 不阻塞
    assert "sh12" not in {s.poi_id for v in stops.values() for s in v}


def test_open_window_respected(shanghai):
    from app.scheduler.constraints import DAY_END
    bo = next(p for p in shanghai if p.id == "sh02")  # 天文馆 16:00 关
    stop, err = can_add(bo, None, HOTEL, DAY_END - 60, 2000.0)
    assert stop is None  # 21:00-60 之后才到,无法在关门内完成 4 小时游览
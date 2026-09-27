"""真实天气:harness 注入 + 优雅降级。全离线(不打真实 API)。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.data.loader import pois_by_id
from app.data.weather import fetch_weather_for_trip, wmo_text
from app.main import app
from app.scheduler.harness import build_context
from tests.conftest import make_participant


def test_wmo_code_mapping():
    assert wmo_text(0) == ("☀️", "晴")
    assert wmo_text(95)[1] == "雷阵雨"
    assert wmo_text(61)[1] == "小雨"
    # 未知代码 / None 给中性值,不炸
    assert wmo_text(None)[1] == "未知"
    assert wmo_text(999)[1] == "未知"


def test_fetch_degrades_without_network(make_trip):
    """★ 回归护栏:无出发时间 / 超出预报范围 → 直接返回 [](不发请求),排程不受影响。"""
    trip = make_trip(participants=[make_participant("A")])
    assert fetch_weather_for_trip(trip) == []          # 无 start_at
    trip.start_at = "2099-01-01T09:00"                 # 远超预报范围
    assert fetch_weather_for_trip(trip) == []
    trip.start_at = "不是日期"                          # 非法值
    assert fetch_weather_for_trip(trip) == []


def test_context_injects_weather_and_guidance(shanghai, make_trip):
    """★ 天气注入 AI 上下文,并给出「按天气+偏好取舍」的指导语。"""
    alice = make_participant("A", must=["sh02"], soft={"must": ["w_indoor"]})
    trip = make_trip(days=2, participants=[alice])
    weather = [
        {"date": "2026-09-27", "icon": "🌧️", "text": "中雨", "tmax": 24.0, "tmin": 19.0, "precip": 80},
        {"date": "2026-09-28", "icon": "☀️", "text": "晴", "tmax": 30.0, "tmin": 22.0, "precip": 10},
    ]
    ctx = build_context(trip, pois_by_id("shanghai"), weather=weather)

    assert "【每日天气" in ctx
    assert "中雨" in ctx and "19~24℃" in ctx and "降水 80%" in ctx   # 第 1 天
    assert "Day2" in ctx and "晴" in ctx and "22~30℃" in ctx          # 第 2 天
    assert "室内" in ctx            # 指导语:雨天优先室内
    assert "偏好室内" in ctx


def test_context_omits_weather_block_when_absent(shanghai, make_trip):
    """取不到天气时不注入空块(AI 看不到任何天气信息,照常排程)。"""
    trip = make_trip(participants=[make_participant("A", must=["sh02"])])
    ctx = build_context(trip, pois_by_id("shanghai"))
    assert "【每日天气" not in ctx


def test_weather_endpoint_degrades_gracefully():
    """API:起点远超预报范围 → days 为空,200 而非报错(前端据此不显示)。"""
    c = TestClient(app)
    t = c.post("/api/trip", json={"city": "shanghai", "days": 2,
                                  "total_budget": 2000, "start_at": "2099-01-01T09:00"}).json()
    r = c.get(f"/api/trip/{t['id']}/weather")
    assert r.status_code == 200 and r.json()["days"] == []
"""真实天气 —— 让 AI 按「天气 + 成员偏好」优化推荐(harness 允许使用真实气候信息)。

数据源 **Open-Meteo**:免费、无需 API key、按经纬度 + 日期返回逐日预报。

设计原则:**任何失败都降级为空**。天气是增强项,绝不能因为它(无网/超时/超范围/解析失败)
让行程生成失败。取不到就静默跳过,排程照常。

调用点:`harness.ai_schedule` 在拼上下文前取一次,注入 build_context;`GET /api/trip/{id}/weather`
供行程页展示。进程内按 (坐标, 日期区间) 记忆化,避免首排+重排重复请求。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 5.0
# 预报可用范围(相对今天):太远/太久以前就不查,直接降级(免得白等一次超时)
MIN_OFFSET_DAYS = -7
MAX_OFFSET_DAYS = 16

_CACHE: dict[tuple, list[dict[str, Any]]] = {}

# WMO 天气代码 → (emoji, 中文)
_WMO: dict[int, tuple[str, str]] = {
    0: ("☀️", "晴"), 1: ("🌤️", "晴间多云"), 2: ("⛅", "多云"), 3: ("☁️", "阴"),
    45: ("🌫️", "有雾"), 48: ("🌫️", "雾凇"),
    51: ("🌦️", "毛毛雨"), 53: ("🌦️", "毛毛雨"), 55: ("🌧️", "大毛毛雨"),
    56: ("🌧️", "冻毛毛雨"), 57: ("🌧️", "冻毛毛雨"),
    61: ("🌦️", "小雨"), 63: ("🌧️", "中雨"), 65: ("🌧️", "大雨"),
    66: ("🌧️", "冻雨"), 67: ("🌧️", "冻雨"),
    71: ("🌨️", "小雪"), 73: ("🌨️", "中雪"), 75: ("❄️", "大雪"), 77: ("🌨️", "雪粒"),
    80: ("🌦️", "阵雨"), 81: ("🌧️", "强阵雨"), 82: ("⛈️", "暴雨"),
    85: ("🌨️", "阵雪"), 86: ("❄️", "强阵雪"),
    95: ("⛈️", "雷阵雨"), 96: ("⛈️", "雷阵雨伴冰雹"), 99: ("⛈️", "强雷暴"),
}


def wmo_text(code: int | None) -> tuple[str, str]:
    """WMO 天气代码 → (emoji, 中文)。未知代码给中性值。"""
    if code is None:
        return "🌡️", "未知"
    return _WMO.get(int(code), ("🌡️", "未知"))


def _at(seq: Any, i: int) -> Any:
    """安全取第 i 项(list 短了也不炸)。"""
    if isinstance(seq, list) and i < len(seq):
        return seq[i]
    return None


def fetch_weather_for_trip(trip) -> list[dict[str, Any]]:
    """按行程的出发日期 + 酒店坐标取逐日天气;取不到返回 `[]`(调用方按"没有天气"处理)。

    返回:[{date, icon, text, tmax, tmin, precip}] 按日期升序。
    """
    start = getattr(trip, "start_at", None)
    if not start:
        return []  # 没设出发时间 → 无日期,不查
    try:
        d0 = datetime.fromisoformat(start).date()
    except (TypeError, ValueError):
        return []

    today = date.today()
    if not (MIN_OFFSET_DAYS <= (d0 - today).days <= MAX_OFFSET_DAYS):
        return []  # 超出预报范围,不浪费一次请求
    d1 = d0 + timedelta(days=max(0, int(getattr(trip, "days", 1)) - 1))

    key = (round(float(trip.hotel_lat), 3), round(float(trip.hotel_lng), 3),
           d0.isoformat(), d1.isoformat())
    if key in _CACHE:
        return _CACHE[key]

    try:
        query = urllib.parse.urlencode({
            "latitude": trip.hotel_lat,
            "longitude": trip.hotel_lng,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "Asia/Shanghai",
            "start_date": d0.isoformat(),
            "end_date": d1.isoformat(),
        })
        with urllib.request.urlopen(f"{OPEN_METEO}?{query}", timeout=TIMEOUT_S) as resp:
            payload = json.load(resp)
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        out: list[dict[str, Any]] = []
        for i, ds in enumerate(times):
            icon, text = wmo_text(_at(daily.get("weather_code"), i))
            out.append({
                "date": ds, "icon": icon, "text": text,
                "tmax": _at(daily.get("temperature_2m_max"), i),
                "tmin": _at(daily.get("temperature_2m_min"), i),
                "precip": _at(daily.get("precipitation_probability_max"), i),
            })
        _CACHE[key] = out
        return out
    except Exception:
        return []  # 无网/超时/解析失败 —— 降级,不影响排程

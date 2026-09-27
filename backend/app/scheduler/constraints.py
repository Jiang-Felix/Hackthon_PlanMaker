"""时空/预算约束 —— 硬性否决条件,违反即剪枝。

时间用「当日分钟数」表示:0:00 = 0,9:00 = 540,21:00 = 1260。
移动模型:haversine 距离 ≤2km 步行(4km/h),否则打车(30km/h);
打车费 = 3 元起步 + 2.6 元/km(超出 3km 部分)。
"""

from __future__ import annotations

import math

from ..models import DayStop, POI

DAY_START = 9 * 60  # 09:00
DAY_END = 21 * 60   # 21:00

WALK_SPEED_KMH = 4.0
TAXI_SPEED_KMH = 30.0
WALK_RADIUS_KM = 2.0
TAXI_BASE = 3.0
TAXI_PER_KM = 2.6
TAXI_FREE_KM = 3.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点大圆距离(公里)。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def transit(from_poi: POI | None, to_poi: POI, hotel: tuple[float, float]) -> tuple[float, float, str, float]:
    """从上一个停留点(或酒店)到 to_poi:返回 (耗时分钟, 花费, 方式, 距离km)。"""
    if from_poi is None:
        lat, lng = hotel
    else:
        lat, lng = from_poi.lat, from_poi.lng
    d = haversine_km(lat, lng, to_poi.lat, to_poi.lng)
    if d <= WALK_RADIUS_KM:
        minutes = d / WALK_SPEED_KMH * 60
        return minutes, 0.0, "步行", d
    minutes = d / TAXI_SPEED_KMH * 60
    cost = TAXI_BASE + TAXI_PER_KM * max(0.0, d - TAXI_FREE_KM)
    return minutes, cost, "打车", d


def parse_open(open_str: str) -> tuple[int, int]:
    """'09:00-17:00' -> (540, 1020);'00:00-23:59' -> (0, 1439)。"""
    try:
        start, end = open_str.split("-")
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        return sh * 60 + sm, min(eh * 60 + em, 1439)
    except Exception:
        return DAY_START, DAY_END


def earliest_start(poi: POI) -> int:
    """该 POI 当日可开始的最早时刻 = 开放与当日窗口的交集起点。"""
    os, _ = parse_open(poi.open)
    return max(os, DAY_START)


def latest_end(poi: POI) -> int:
    """该 POI 当日可结束的最晚时刻。"""
    _, oe = parse_open(poi.open)
    return min(oe, DAY_END)


def can_add(
    poi: POI,
    from_poi: POI | None,
    hotel: tuple[float, float],
    cur_minute: int,
    remaining_budget: float,
    headcount: int = 1,
) -> tuple[DayStop, None] | tuple[None, str]:
    """判断能否把 poi 追加到当前时刻 cur_minute(上一个停留的结束时刻)。

    返回 (新增的 DayStop, None) 或 (None, 拒绝原因)。

    `remaining_budget` 是「门票+交通」的可用预算(总预算已扣掉食宿),`headcount`
    是同行人数 —— 门票按**每人**计(poi.price × N 人),打车是共享一趟(×1)。
    """
    travel_min, travel_cost, mode, _ = transit(from_poi, poi, hotel)
    travel_min = int(round(travel_min))
    arrive = cur_minute + travel_min
    es, le_f = earliest_start(poi), latest_end(poi)
    duration = poi.hours * 60
    if arrive > le_f:
        return None, f"到达时它已经关门了(开放时间 {poi.open})"
    start = max(arrive, es)
    end = start + duration
    if end > le_f:
        return None, (f"放不进当天的剩余时间 —— 它 {poi.open} 开放、要玩 {poi.hours:g} 小时,"
                      f"建议放当天更早、或换一天")
    # 门票按人头计、打车全队共享一趟。文案**不带景点名**(调用方会补上下文),
    # 也不显示 ¥0 门票 —— 免费就直说,写"门票 ¥0×4 人 = ¥0"只会让人困惑。
    n = max(1, headcount)
    group_cost = poi.price * n
    if travel_cost + group_cost > remaining_budget:
        if group_cost == 0 and travel_cost == 0:
            # 免费且步行,却仍"超预算" → 真实原因是剩余预算已被用到 0/负数
            return None, "剩余预算已用完,排不进任何景点"
        cost_desc = (f"门票 ¥{poi.price:.0f}/人 × {n} 人 + 车费 ¥{travel_cost:.0f}"
                     if poi.price > 0 else f"车费 ¥{travel_cost:.0f}")
        return None, f"会超出剩余预算({cost_desc})"
    stop = DayStop(
        poi_id=poi.id,
        name=poi.name,
        emoji=poi.emoji,
        arrive_min=arrive,
        start_min=start,
        end_min=end,
        travel_min=int(round(travel_min)),
        travel_mode=mode,
        travel_cost=round(travel_cost, 1),
        price=poi.price,
        tags=poi.tags,
    )
    return stop, None


def fmt_minute(m: int) -> str:
    h, mm = divmod(m, 60)
    if h >= 24:
        h %= 24
    return f"{h:02d}:{mm:02d}"
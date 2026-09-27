"""食宿与经济口径 —— 全队总预算下的基本消费(评审「经济计算是否正确」的落点)。

2026-09-27 审计后定型:
- **总预算 = 全队合计花销** = 门票(人均 × N 人)+ 打车(全队共享,按趟 ×1)+ 餐饮 + 住宿。
- 食宿是**固定承诺**,先从总预算里扣掉;门票+打车在「剩余可用预算」里竞争。
- 食宿可「自动」(按成员消费/住宿偏好估)或「手动」(规则页填)。

旧实现的两个缺陷在这里被钉死:
1. 门票只按一次计 —— N>1 时预算虚高 N 倍(本模块用 headcount 乘)。
2. 完全不算食宿 —— 多天行程住宿常是大头(此处引入 predictive 的按偏好估计或手动值)。
"""

from __future__ import annotations

from ..models import TripState

DEFAULT_FOOD_PER_HEAD = 90.0
DEFAULT_LODGING_PER_HEAD = 180.0

_BUDGET_TAGS = ("sp_budget",)                      # 严格控预算
_LUX_TAGS = ("sp_over", "sp_food", "sp_sight")     # 舍得花/超支不介意
_HOSTEL_TAGS = ("lo_hostel", "lo_cheap")           # 民宿/价格优先
_HOTEL_TAGS = ("lo_hotel", "lo_center")            # 酒店/位置优先


def _soft_has(participants, tags: tuple[str, ...]) -> bool:
    """任一成员在 must/want/ok 里声明了这些偏好标签(refuse 不算「想要」)。"""
    for p in participants:
        for lv in ("must", "want", "ok"):
            for t in getattr(p.soft, lv):
                if t in tags:
                    return True
    return False


def estimate_essentials(participants) -> tuple[float, float]:
    """「自动」模式:按成员偏好(消费倾向/住宿/饮食)估计每人每天餐费 + 每晚住宿。

    消费倾向(优先级:控预算 > 舍得花 > 默认):
    - sp_budget(严格控预算)→ 餐 65 / 宿 90
    - sp_over / sp_food / sp_sight(舍得花)→ 餐 130 / 宿 260
    - 默认 → 餐 90 / 宿 180
    住宿再叠加偏好:lo_hostel/lo_cheap → 宿 90;lo_hotel/lo_center → 宿 260。
    """
    if _soft_has(participants, _BUDGET_TAGS):
        food, lodging = 65.0, 90.0
    elif _soft_has(participants, _LUX_TAGS):
        food, lodging = 130.0, 260.0
    else:
        food, lodging = DEFAULT_FOOD_PER_HEAD, DEFAULT_LODGING_PER_HEAD

    if _soft_has(participants, _HOSTEL_TAGS):
        lodging = 90.0
    elif _soft_has(participants, _HOTEL_TAGS):
        lodging = 260.0
    return food, lodging


def sync_essentials(trip: TripState) -> None:
    """把 trip 的食宿单价刷成当前生效值:auto 按偏好估计,manual 保留用户填的。"""
    if trip.budget_mode == "manual":
        return
    trip.food_per_head, trip.lodging_per_head = estimate_essentials(trip.participants)


def essentials_total(trip: TripState) -> float:
    """全队食宿合计 = (餐 + 宿) × N 人 × days 天。"""
    n = len(trip.participants)
    return max(0.0, (trip.food_per_head + trip.lodging_per_head) * n * trip.days)


def disposable_budget(trip: TripState) -> float:
    """门票+交通的可用预算 = 总预算 - 食宿(固定承诺先扣)。"""
    return max(0.0, trip.total_budget - essentials_total(trip))
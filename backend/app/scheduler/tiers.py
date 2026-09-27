"""偏好分层 —— 组委会要求的取舍原则:硬约束 > 强偏好 > 一般偏好。

weight 用于**排序与解释**(哪个层级更重要),refuse 为硬排除(参与即拒,排程时根本不会成为候选)。
must 的权重是 ok 的 10 倍 —— 天然防平均主义:满足 1 个 must 比满足 3 个 ok 更值。

注意:原 `satisfaction` / `declared_weight` / `satisfied_weight` 已删除。它们是给白盒
优化器用的**相对**目标函数(只求可比,绝对值无意义),白盒移除后却被当成面向用户的
绝对百分比展示,导致"容量排不下"被算成"公平失败"、零声明成员被判 0% 等缺陷。
现在的公平口径见 fairness.py(容量感知的人均配额)。
"""

from __future__ import annotations

from typing import Callable, TypeVar

from ..models import StructuredPref, TagPref

_LEVELS_ALL = ("refuse", "must", "want", "ok")

# 层级 -> 权重。refuse 用极小负权替代 -inf,便于数值计算。
# 仅用于「哪个层级更优先」的排序与解释文案(explanation.py),不再参与满意度计算。
WEIGHT: dict[str, float] = {"refuse": -1e9, "must": 10.0, "want": 4.0, "ok": 1.0}

LEVELS = ("must", "want", "ok")  # refuse 单独处理

P = TypeVar("P")


def _sanitize_like(pref, factory: Callable[[], P]) -> P:
    """四层去重:同一 id 只归入最高优先级层级(拒绝>必去>想去>可接受)。"""
    out = factory()
    seen: set[str] = set()
    for level in _LEVELS_ALL:
        keep = []
        for pid in getattr(pref, level):
            if pid in seen:
                continue
            seen.add(pid)
            keep.append(pid)
        setattr(out, level, keep)
    return out


def _merge_like(base, extra, factory: Callable[[], P]) -> P:
    """增量合并:extra 提到的 id 以其新层级为准,未提到的原样保留,仍互斥。"""
    merged: dict[str, list[str]] = {lv: list(getattr(base, lv)) for lv in _LEVELS_ALL}
    mentioned: set[str] = {pid for lv in _LEVELS_ALL for pid in getattr(extra, lv)}
    for lv in _LEVELS_ALL:
        merged[lv] = [pid for pid in merged[lv] if pid not in mentioned]
    for lv in _LEVELS_ALL:
        merged[lv].extend(getattr(extra, lv))
    return _sanitize_like(factory(**merged), factory)


def sanitize_pref(pref: StructuredPref) -> StructuredPref:
    """POI 偏好去重(评审要求「同一地点只出现在一个意愿类别」)。"""
    return _sanitize_like(pref, StructuredPref)


def merge_prefs(base: StructuredPref, extra: StructuredPref) -> StructuredPref:
    """POI 偏好增量合并:「再补充几句」语义 —— 在原有倾向上叠加,不抹历史。"""
    return _merge_like(base, extra, StructuredPref)


def sanitize_tag_pref(pref: TagPref) -> TagPref:
    """扩展软偏好去重(与 POI 偏好同规则,独立 id 空间)。"""
    return _sanitize_like(pref, TagPref)


def merge_tag_pref(base: TagPref, extra: TagPref) -> TagPref:
    """扩展软偏好增量合并(与 merge_prefs 同语义)。"""
    return _merge_like(base, extra, TagPref)

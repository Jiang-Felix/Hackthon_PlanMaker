"""测试替身 —— 白盒引擎移除后,用脚本化草案保证回归可确定性复现。

注意:这是**测试专用**装置,不进产品代码。产品路径只有真 AI(DeepSeek)。
"""

from __future__ import annotations

import json

from app.models import RecoSettings, StructuredPref, TagPref


def draft(*days_of_ids) -> str:
    """构造一份合法的 AI 草案 JSON:每个参数是一天的 poi_id 列表。"""
    return json.dumps(
        {"days": [{"day": i, "stops": list(ids)} for i, ids in enumerate(days_of_ids)]},
        ensure_ascii=False,
    )


class FakeProvider:
    """按脚本回放草案:首次调用弹第一个,后续 revise 依次弹出。

    `soft` 是软偏好自评结果({participant_id: {satisfied, missed, violated}}),
    默认空 = 未评估(soft_rate 落 None)。注意必须显式实现 assess_soft ——
    否则 ai_plan/replan 里那层 `except Exception -> {}` 会把 AttributeError 一起吞掉,
    让软偏好这条路径变得**测不到**。
    """

    name = "fake"

    def __init__(self, *drafts: str, soft: dict | None = None):
        self._queue = list(drafts)
        self.last_context = ""
        self.revise_calls: list[str] = []
        self.soft = soft or {}
        self.assess_calls = 0

    def draft_itinerary(self, trip, pois, context: str) -> str:
        self.last_context = context
        return self._queue.pop(0) if self._queue else "{}"

    def revise_itinerary(self, draft_text: str, issues: str, context: str = "") -> str:
        self.revise_calls.append(issues)
        return self._queue.pop(0) if self._queue else draft_text

    def assess_soft(self, trip, stops_by_day, vocab) -> dict:
        self.assess_calls += 1
        return self.soft

    # 解析类接口:FakeProvider 不参与,返回空
    def parse_text(self, text: str, pois) -> StructuredPref:
        return StructuredPref()

    def parse_soft_prefs(self, text: str, vocab) -> TagPref:
        return TagPref()

    def parse_reco_settings(self, text: str) -> RecoSettings:
        return RecoSettings()

    def hydrate(self, text: str, pois) -> StructuredPref:
        return StructuredPref()

    def explain(self, trace: dict) -> str:
        return ""


def patch_provider(monkeypatch, provider) -> None:
    """把 harness 里的 get_provider 换掉(FakeProvider 只影响 AI 编排路径)。"""
    from app.scheduler import harness

    monkeypatch.setattr(harness, "get_provider", lambda: provider)
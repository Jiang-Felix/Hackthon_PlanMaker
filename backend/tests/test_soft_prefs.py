"""扩展软偏好 + 全局推荐设置的 AI 解析测试(评审 User Input / Recommendation Logic)。"""

from __future__ import annotations

from app.ai.provider import get_provider
from app.data.loader import vocab_tags


def _parse_soft(text: str):
    return get_provider().parse_soft_prefs(text, vocab_tags())


def _parse_settings(text: str):
    return get_provider().parse_reco_settings(text)


# ---------------------------------------------------------------- 软偏好
def test_soft_energy_light():
    """「怕累不想走太多」→ 体力·轻松为主(否定式别名应升为 must,而不是被当成 refuse)。"""
    p = _parse_soft("我怕累,不想走太多")
    assert "en_light" in p.must
    assert "en_light" not in p.refuse


def test_soft_weather_rain_no():
    p = _parse_soft("下雨就不想出门了")
    assert "w_rain_no" in p.must


def test_soft_rhythm_and_diet():
    p = _parse_soft("我要睡到自然醒,不吃辣")
    assert "rh_late" in p.must
    assert "di_mild" in p.must


def test_soft_multiple_categories():
    p = _parse_soft("能暴走,喜欢走路,可以吃辣,接受夜宵")
    flat = p.must + p.want + p.ok + p.refuse
    for tid in ("en_hard", "tr_walk", "di_spicy", "di_supper"):
        assert tid in flat, tid


def test_soft_empty_when_nothing_matched():
    p = _parse_soft("今天天气不错")
    assert not (p.must or p.want or p.ok or p.refuse)


# ---------------------------------------------------------------- 全局推荐设置
def test_settings_conflict_strategy():
    assert _parse_settings("我们希望分组行动,各自逛各自的").conflict_strategy == "split"
    assert _parse_settings("这次该谁优先就谁优先,轮换来").conflict_strategy == "rotate"


def test_settings_schedule_align():
    assert _parse_settings("希望能早点结束整个行程").schedule_align == "left"
    assert _parse_settings("每天都要有活动,尽量排满").schedule_align == "fill"


def test_settings_activity_priorities_ordered():
    s = _parse_settings("首先别安排重复的,然后同类型的尽量放一起")
    assert s.activity_priorities[:2] == ["avoid_similar", "cluster_theme"]


def test_settings_numbers():
    s = _parse_settings("景点之间留白 20 分钟,排队最多 45 分钟")
    assert s.buffer_min == 20
    assert s.max_wait_min == 45


def test_settings_defaults_when_no_signal():
    s = _parse_settings("随便啦")
    assert s.conflict_strategy == "rotate"
    assert s.schedule_align == "fill"
    assert s.buffer_min == 15

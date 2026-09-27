"""Mock AI 解析回归测试:模糊匹配 + 偏好互斥(评审两点反馈)。"""

from __future__ import annotations

from typing import Any

from app.ai.provider import get_provider
from app.data.loader import load_city
from app.models import POI, StructuredPref
from app.scheduler.tiers import sanitize_pref


def _parse(text: str, pois: list[POI]) -> StructuredPref:
    return get_provider().hydrate(text, pois)


def test_fuzzy_nickname_matching(shanghai):
    """评审1:不应只能全字符匹配,昵称/描述应可模糊命中。"""
    pref = _parse("我特别想看东方明珠的夜景", shanghai)
    assert "sh09" in pref.want  # 东方明珠 -> 东方明珠塔(别名)


def test_alias_across_cities(chengdu):
    pref = _parse("一定要去看熊猫滚滚", chengdu)
    assert "cd01" in pref.must  # 熊猫 -> 成都大熊猫基地


def test_positive_specific_overrides_generic_refuse(shanghai):
    """想去水族馆(具体点名)不被『不想去乐园』(类别级拒绝)误伤。"""
    pref = _parse("想去水族馆看企鹅,不想去乐园", shanghai)
    assert "sh13" in pref.want      # 海昌被具体点名,保留
    assert "sh12" in pref.refuse    # 迪士尼只被类别拒绝


def test_structured_dedupe_across_levels():
    """评审2:同一地点只能出现在一个意愿层级(高优先级者胜)。"""
    sp = sanitize_pref(StructuredPref(
        refuse=["sh12"], must=["sh12", "sh02"], want=["sh02"]
    ))
    assert sp.refuse == ["sh12"]
    assert sp.must == ["sh02"]
    assert sp.want == []
    flat: list[str] = [p for v in sp.model_dump().values() for p in v]
    assert len(flat) == len(set(flat))  # 总数 = 去重后总数


def test_parse_result_is_disjoint(shanghai):
    """NL 解析同样保证同点不跨层。「想去天文馆&必须去天文馆」只进 must。"""
    pref = _parse("我超想去天文馆,天文馆必须去,顺便去水族馆", shanghai)
    assert "sh02" in pref.must
    assert "sh02" not in pref.want
    assert "sh02" not in pref.ok
    flat: list[str] = [p for v in pref.model_dump().values() for p in v]
    assert len(flat) == len(set(flat))


def test_merge_prefs_is_incremental():
    """「再补充几句」:在原有基础上合并 —— 不抹历史、新表述调整层级、保持互斥。"""
    from app.scheduler.tiers import merge_prefs

    base = StructuredPref(must=["sh12"],                 # 迪士尼必去
                          want=["sh02"],                 # 天文馆想去
                          ok=["sh05", "sh06"])           # 两条美食可接受
    extra = StructuredPref(want=["sh23"], refuse=["sh12"])  # 补充:想看朱家角,不去迪士尼了
    merged = merge_prefs(base, extra)
    assert merged.model_dump() == {
        "must": [],                  # 迪士尼被「不去」挪走,不再必去
        "want": ["sh02", "sh23"],    # 历史保留 + 新补充的朱家角
        "ok": ["sh05", "sh06"],      # 历史可接受一项不丢
        "refuse": ["sh12"],
    }


def test_merge_prefs_upgrade_level():
    """补充里说「必须去天文馆」会把原来只是想去的升为必去。"""
    from app.scheduler.tiers import merge_prefs

    base = StructuredPref(want=["sh02"], ok=["sh05"])
    merged = merge_prefs(base, StructuredPref(must=["sh02"]))
    assert merged.must == ["sh02"]
    assert merged.want == []
    assert merged.ok == ["sh05"]
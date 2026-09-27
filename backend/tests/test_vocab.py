"""词表 + 扩展软偏好 + 全局推荐设置 的测试。"""

from __future__ import annotations

from app.data.loader import (
    load_preference_vocab,
    reco_options,
    vocab_tag_ids,
    vocab_tags,
)
from app.models import StructuredPref, TagPref
from app.scheduler.tiers import merge_tag_pref, sanitize_tag_pref


# ---------------------------------------------------------------- 词表
def test_vocab_loads_and_is_wellformed():
    vocab = load_preference_vocab()
    assert vocab["version"] >= 1
    cats = vocab["categories"]
    assert len(cats) >= 10  # 出行/体力/天气/消费/作息/密度/紧迫度/住宿/社交/饮食

    ids = [t["id"] for c in cats for t in c["tags"]]
    assert len(ids) == len(set(ids)), "tag id 必须全局唯一"
    for c in cats:
        assert c["key"] and c["label"]
        assert len(c["tags"]) >= 2, f"类别 {c['key']} 标签过少"


def test_vocab_tags_flattened_fields():
    tags = vocab_tags()
    assert len(tags) > 25
    t = next(t for t in tags if t.id == "en_light")
    assert t.label == "轻松为主"
    assert t.category == "energy"
    assert t.category_label == "体力分配"
    assert "怕累" in t.aliases


def test_vocab_tag_ids_match_flattened():
    assert vocab_tag_ids() == frozenset(t.id for t in vocab_tags())


def test_reco_options_present():
    opts = reco_options()
    assert {o["id"] for o in opts["conflict_strategy"]} == {"rotate", "split", "majority"}
    assert {o["id"] for o in opts["schedule_align"]} == {"left", "center", "right", "fill"}
    assert len(opts["activity_priorities"]) >= 3


# ---------------------------------------------------------------- TagPref 卫生
def test_sanitize_tag_pref_is_disjoint():
    out = sanitize_tag_pref(TagPref(refuse=["en_light"], must=["en_light", "w_rain_no"], want=["w_rain_no"]))
    assert out.refuse == ["en_light"]
    assert out.must == ["w_rain_no"]
    assert out.want == []


def test_merge_tag_pref_is_incremental():
    base = TagPref(must=["en_light"], ok=["di_spicy"])
    extra = TagPref(want=["w_rain_no"], refuse=["en_light"])  # 改口:不想要轻松了
    merged = merge_tag_pref(base, extra)
    assert merged.must == []
    assert merged.refuse == ["en_light"]
    assert merged.want == ["w_rain_no"]
    assert merged.ok == ["di_spicy"]  # 历史保留


def test_tag_pref_does_not_pollute_structured_pref():
    """两个 id 空间相互独立,StructuredPref 的 sanitize 不受影响。"""
    sp = StructuredPref(must=["sh02"], want=["sh05"])
    assert sp.refuse == [] and sp.ok == []
    tp = TagPref(must=["en_light"])
    assert tp.refuse == [] and tp.want == []

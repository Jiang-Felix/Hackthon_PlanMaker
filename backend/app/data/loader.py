"""载入内置城市 POI 数据与扩展偏好词表。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..models import POI, VocabTag

_CITIES_DIR = Path(__file__).parent / "cities"
_VOCAB_PATH = Path(__file__).parent / "preference_vocab.json"


@lru_cache(maxsize=None)
def load_city(city: str) -> list[POI]:
    """按城市标识(shanghai/hangzhou/chengdu)载入 POI 列表。"""
    path = _CITIES_DIR / f"{city.lower()}.json"
    if not path.exists():
        raise KeyError(f"未知城市: {city},可用: {', '.join(available_cities())}")
    with open(path, encoding="utf-8") as f:
        return [POI.model_validate(item) for item in json.load(f)]


def available_cities() -> list[str]:
    return sorted(p.stem for p in _CITIES_DIR.glob("*.json"))


def pois_by_id(city: str) -> dict[str, POI]:
    return {poi.id: poi for poi in load_city(city)}


# ---------------------------------------------------------------- 扩展偏好词表
@lru_cache(maxsize=None)
def load_preference_vocab() -> dict:
    """载入扩展软偏好词表(类别→标签→aliases + 全局推荐选项)。"""
    with open(_VOCAB_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def vocab_tags() -> list[VocabTag]:
    """词表扁平化为标签列表,供 mock 解析 / harness 上下文 / 前端榜单池三方共用。"""
    vocab = load_preference_vocab()
    out: list[VocabTag] = []
    for cat in vocab.get("categories", []):
        for tag in cat.get("tags", []):
            out.append(VocabTag(
                id=tag["id"],
                label=tag["label"],
                emoji=tag.get("emoji", cat.get("emoji", "🏷️")),
                category=cat["key"],
                category_label=cat.get("label", cat["key"]),
                aliases=tag.get("aliases", []),
            ))
    return out


@lru_cache(maxsize=None)
def vocab_tag_ids() -> frozenset[str]:
    return frozenset(t.id for t in vocab_tags())


def reco_options() -> dict:
    """全局推荐设置的可选项(前端控件 + AI 提示共用)。"""
    return load_preference_vocab().get("reco_options", {})
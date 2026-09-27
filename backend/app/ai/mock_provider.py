"""Mock AI 提供方 —— 规则解析与模板解释,演示零网络依赖。"""

from __future__ import annotations

from ..errors import ProviderError
from ..models import POI, RecoSettings, StructuredPref, TagPref
from ..scheduler.tiers import sanitize_tag_pref
from .provider import LLMProvider

# 情绪强度标记 -> 层级
_MUST = ("必去", "一定", "必须", "超想", "强烈", "非去不可", "就要", "无论如何", "我要")
_WANT = ("想去", "想看", "想玩", "想逛", "想喝", "想吃", "想见", "我想", "希望", "期待", "特别想", "很感兴趣", "可以安排")
_REFUSE = ("不去", "不想", "不要", "拒绝", "讨厌", "怕", "恐", "过敏", "千万别", "坚决", "反感", "受不了")
_OK = ("可以", "还行", "能接受", "无所谓", "愿意", "都行", "顺便")

# 词 -> 偏好标签(与城市 POI tags 对齐)。名称子串匹配优先级最高。
_TAG_KW = {
    "逛展": ("逛展", "看展", "美术馆", "展览"),
    "博物馆": ("博物馆", "博物院"),
    "科普": ("科普", "科学", "科技", "天文", "星空"),
    "亲子": ("亲子", "孩子", "带娃", "小朋友", "遛娃"),
    "乐园": ("乐园", "游乐园", "过山车", "迪士尼", "游乐"),
    "美食": ("吃", "美食", "小吃", "火锅", "串串", "甜品", "点心", "吃辣", "口味"),
    "购物": ("买", "购物", "逛街", "商场", "逛街买"),
    "户外": ("户外", "自然", "公园", "散步", "草坪", "骑行", "湿地"),
    "徒步": ("徒步", "爬山", "登山", "走远"),
    "寺庙": ("寺庙", "古刹", "寺院", "拜佛"),
    "历史": ("历史", "古迹", "古镇", "古建筑", "文物"),
    "观景": ("观景", "登高", "看景", "塔", "高处"),
    "夜景": ("夜景", "灯光", "晚上看", "夜"),
    "艺术": ("艺术", "画廊", "当代艺术"),
    "文创": ("文创", "手作", "创意园", "文艺"),
    "街区": ("街区", "老街", "巷子", "逛巷子", "马路"),
    "赏花": ("赏花", "花", "樱花", "植物", "桂花"),
    "茶馆": ("茶", "茶馆", "盖碗茶", "喝下午茶"),
    "演出": ("演出", "表演", "剧场", "看戏"),
    "海洋馆": ("海洋", "水族", "海洋馆"),
    "夜宵": ("夜宵", "夜市", "烧烤"),
    "动物": ("动物", "熊猫", "小动物", "看滚滚"),
    "公园": ("公园",),
}

_SPLIT = ("，", ",", "、", "。", ";", "；", "以及", "和", "跟", "还有", "顺便", "重点", "然后")


class MockProvider(LLMProvider):
    name = "mock"

    def parse_text(self, text: str, pois: list[POI]) -> StructuredPref:
        pref = StructuredPref()
        positive_specific: set[str] = set()   # 被具体点名(名称/别名)并被正面诉求的 POI
        negative_specific: set[str] = set()   # 被具体点名且被明确拒绝的 POI
        for clause in _split_into_clauses(text):
            clause = clause.strip()
            if not clause:
                continue
            level = _detect_level(clause)
            matched, specific = _match_clause(clause, pois)
            if specific:
                if level == "refuse":
                    negative_specific.update(matched)
                else:
                    positive_specific.update(matched)
            bucket = getattr(pref, level)
            for pid in matched:
                if pid not in bucket:
                    bucket.append(pid)
        # 具体点名的正面诉求优先于类别级拒绝(想去水族馆 ≠ 不去乐园而拒掉它)
        protected = positive_specific - negative_specific
        pref.refuse = [x for x in pref.refuse if x not in protected]
        return _sanitize(pref)

    def explain(self, trace: dict) -> str:
        reasons = trace.get("reasons", [])
        poi = trace.get("poi", "")
        if not reasons:
            return f"{poi}:暂无可解释的决策信息"
        head = "保留" if trace.get("included") else "未纳入"
        return f"{poi} {head}:" + "；".join(reasons)

    def draft_itinerary(self, trip, pois: "dict[str, POI]", context: str) -> str:
        """mock 不再具备排程能力 —— 白盒决策引擎已按要求移除。

        移除白盒后,行程生成完全交给真 AI(DeepSeek)。这里**显式报错**,而不是
        返回空草案造成「静默失败」的误判。
        """
        raise ProviderError(
            "当前环境未接入 AI,暂时无法生成行程。请稍后重试,或联系管理员。"
        )

    def assess_soft(self, trip, stops_by_day, vocab) -> dict:
        """软偏好自评同样是**语义判断**,规则法做不了 —— 返回空表示"未评估"。

        空字典会让 soft_rate 落 None(而不是 0),公平页显示"未评估"而非
        "你的偏好全没被照顾" —— 这正是新口径刻意区分的两件事。
        """
        return {}

    def parse_soft_prefs(self, text: str, vocab: list) -> TagPref:
        """把自然语言里的模糊软偏好解析为词表标签分级。

        两个关键启发式:
        1. **最长别名优先 + 区间占位** —— 避免「不吃辣」同时命中 di_mild 的「不吃辣」
           和 di_spicy 的「吃辣」(后者被更长的匹配占位后跳过)。
        2. **否定式别名** —— 别名自带否定词(「怕累」「不想走太多」「下雨不想出门」)
           时,它表达的是**强烈正向诉求**,落 must 而非 refuse。
           反之,否定词在别名之外(「不想吃夜宵」中的「吃夜宵」)则保留 refuse 语义。
        """
        pref = TagPref()
        neg_words = _REFUSE + ("不吃", "不喝", "不爱", "不喜欢", "不能", "别", "避免", "受不了")
        for clause in _split_into_clauses(text):
            clause = clause.strip()
            if not clause:
                continue
            level = _detect_level(clause)
            hits: list[tuple[int, int, str, str]] = []  # (长度, 起点, 命中文本, tag id)
            for tag in vocab:
                for name in (tag.label, *tag.aliases):
                    idx = clause.find(name) if name else -1
                    if idx >= 0:
                        hits.append((len(name), idx, name, tag.id))
            hits.sort(key=lambda h: -h[0])
            consumed: list[tuple[int, int]] = []
            for ln, idx, name, tid in hits:
                span = (idx, idx + ln)
                if any(not (span[1] <= c[0] or span[0] >= c[1]) for c in consumed):
                    continue  # 与更长的匹配重叠 → 跳过
                consumed.append(span)
                eff = "must" if any(w in name for w in neg_words) else level
                bucket = getattr(pref, eff)
                if tid not in bucket:
                    bucket.append(tid)
        return sanitize_tag_pref(pref)

    def parse_reco_settings(self, text: str) -> RecoSettings:
        """把自然语言里的全局推荐诉求解析为设置(关键词 + 数值正则)。"""
        import re

        from ..data.loader import reco_options

        s = RecoSettings()
        opts = reco_options()

        def _match(group: str) -> str | None:
            for item in opts.get(group, []):
                if item["label"] in text or any(a in text for a in item.get("aliases", [])):
                    return item["id"]
            return None

        cs = _match("conflict_strategy")
        if cs:
            s.conflict_strategy = cs  # type: ignore[assignment]
        sa = _match("schedule_align")
        if sa:
            s.schedule_align = sa  # type: ignore[assignment]

        # 活动关联优先级:按出现位置排序
        found: list[tuple[int, str]] = []
        for item in opts.get("activity_priorities", []):
            for kw in [item["label"], *item.get("aliases", [])]:
                idx = text.find(kw)
                if idx >= 0:
                    found.append((idx, item["id"]))
                    break
        s.activity_priorities = [pid for _, pid in sorted(found)]

        buf = re.search(r"(?:留白|缓冲|休息)[^\d]{0,6}(\d{1,3})\s*分", text)
        if buf:
            s.buffer_min = min(180, int(buf.group(1)))
        wait = re.search(r"(?:等待|排队)[^\d]{0,6}(?:不超|最多|上限)?[^\d]{0,4}(\d{1,3})\s*分", text)
        if wait:
            s.max_wait_min = min(180, int(wait.group(1)))
        return s


def _split_into_clauses(text: str) -> list[str]:
    parts = [text]
    for sep in _SPLIT:
        parts = [p for seg in parts for p in seg.split(sep) if p.strip()]
    return parts


def _detect_level(clause: str) -> str:
    if any(k in clause for k in _REFUSE):
        return "refuse"
    if any(k in clause for k in _MUST):
        return "must"
    if any(k in clause for k in _WANT):
        return "want"
    if any(k in clause for k in _OK):
        return "ok"
    return "ok"


def _match_clause(clause: str, pois: list[POI]) -> tuple[list[str], bool]:
    """返回 (命中的 POI id 列表, 是否具体点名)。

    specific=True 表示该句点名了具体地点(完整名/别名/紧凑名),而非宽泛类别(标签)。
    """
    name_hits = _match_by_name(clause, pois)
    if name_hits:
        return name_hits, True
    hits: list[str] = []
    for tag, kws in _TAG_KW.items():
        if any(kw in clause for kw in kws):
            hits += [p.id for p in pois if tag in p.tags]
    return list(dict.fromkeys(hits)), False


_CITY_PREFIX = ("上海", "杭州", "成都")
_GENERIC_SUFFIX = ("古镇", "乐园", "步行街", "古街", "街区", "景区", "遗址",
                   "大厦", "广场", "中心", "湿地", "公园", "基地", "文创园")


def _match_by_name(clause: str, pois: list[POI]) -> list[str]:
    """地点级匹配:完整名 / 别名昵称 / 紧凑名(去城市前缀+通用后缀)。

    例:「想去东方明珠」→ 上海东方明珠塔(别名);「去看熊猫」→ 成都大熊猫基地(别名)。
    命中具体地点时优先返回,避免落到宽泛的标签匹配。
    """
    # 1) 完整名
    hits = [p.id for p in pois if p.name in clause]
    if hits:
        return hits
    # 2) 别名/昵称
    alias_hits: list[tuple[str, str]] = []
    for p in pois:
        for a in p.aliases:
            if a.lower() in clause.lower():
                alias_hits.append((p.id, a))
    if alias_hits:
        # 命中词越长越特异 → 优先
        ranked = sorted(alias_hits, key=lambda kv: -len(kv[1]))
        return list(dict.fromkeys(pid for pid, _ in ranked))
    # 3) 紧凑名:去城市前缀 + 通用后缀(朱家角古镇 -> 朱家角;上海迪士尼乐园 -> 迪士尼)
    compact: dict[str, str] = {}
    for p in pois:
        bare = p.name
        for prefix in _CITY_PREFIX:
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
                break
        for suffix in _GENERIC_SUFFIX:
            if bare.endswith(suffix):
                bare = bare[: -len(suffix)]
                break
        if bare and len(bare) >= 2 and bare in clause:
            compact[p.id] = bare
    if compact:
        ranked = sorted(compact.items(), key=lambda kv: -len(kv[1]))
        return [pid for pid, _ in ranked]
    return []


def _sanitize(pref: StructuredPref) -> StructuredPref:
    """解析后统一去重:同一地点只保留最高优先级层级。"""
    from ..scheduler.tiers import sanitize_pref
    return sanitize_pref(pref)
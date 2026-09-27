"""OpenAI 兼容的 LLM 提供方 —— 真实模型接入(类名保留 DeepSeekProvider 以便兼容)。

可指向任意 OpenAI 兼容端点。环境变量(**通用名优先**,旧的 DEEPSEEK_* 仍兼容):
  LLM_PROVIDER=deepseek         # 启用真实模型(否则 mock,只解析不排程)
  LLM_API_KEY=sk-xxxx           # 或 DEEPSEEK_API_KEY
  LLM_BASE_URL=.../v1           # 或 DEEPSEEK_BASE_URL,默认 https://api.deepseek.com
  LLM_MODEL=<model>             # 或 DEEPSEEK_MODEL,默认 deepseek-chat
  LLM_ASSESS_TIMEOUT=20         # 软偏好自评的单独超时(秒),默认 20

⚠️ `LLM_ASSESS_TIMEOUT` 默认 20s 是按**快模型**定的(快模型约 1s)。换成慢模型
(DeepSeek 同规模载荷约 39s)而不调大,`assess_soft` 会超时并**静默降级为「未评估」**
—— 不报错,只是公平页的软偏好整列变空。

示例(任意 OpenAI 兼容网关):
  LLM_PROVIDER=deepseek
  LLM_API_KEY=sk-xxxx
  LLM_BASE_URL=https://your-gateway.example/v1
  LLM_MODEL=<model>

移除白盒引擎后,本模块是**唯一**能产出行程的路径(见 scheduler/harness.py)。
"""

from __future__ import annotations

import json
import os

import httpx

from ..errors import ProviderError
from ..models import POI, RecoSettings, StructuredPref, TagPref
from .provider import LLMProvider


def _env(*names: str, default: str = "") -> str:
    """按顺序取第一个非空环境变量(通用名优先,兼容旧名)。"""
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return default


def _env_float(name: str, default: float) -> float:
    """取一个浮点环境变量;缺失或写坏了都退回 default(不能因为一个笔误让服务起不来)。"""
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        v = float(raw.strip())
    except ValueError:
        return default
    return v if v > 0 else default

_SOFT_PROMPT = """你是旅行偏好解析助手。把用户这段话里的**模糊软偏好**解析为标签分级,只输出 JSON。

输出格式(JSON):
{{"refuse": ["<标签id>"], "must": ["<标签id>"], "want": ["<标签id>"], "ok": ["<标签id>"]}}

分级定义:
- must:强烈诉求(「必须」「受不了…」「一定要」「怕…」等强烈表述)
- want:明显倾向
- ok:可以接受
- refuse:明确排斥(注意:若用户说的是「不想X」,而 X 本身是负向标签(如「不想走太多」),
  这是**强烈想要「轻松为主」**,应放 must,不要放 refuse)

规则:只能使用下面列出的标签 id,一个都别发明;没提到的一律不要放。

可选标签:
{tag_hint}

用户原话:「{text}」
"""

_SETTINGS_PROMPT = """你是多人旅行行程规划助手。把用户这段话解析为「全局推荐设置」,只输出 JSON。

输出格式(JSON):
{{"conflict_strategy": "rotate|split|majority",
 "schedule_align": "left|center|right|fill",
 "activity_priorities": ["avoid_similar"|"cluster_theme"|"food_balance"],
 "buffer_min": <整数分钟>,
 "max_wait_min": <整数分钟>}}

含义:
- conflict_strategy 冲突解决:rotate=轮换优先 / split=分组出游 / majority=服从多数
- schedule_align 日程对齐:left=左对齐(早结束) / center=居中 / right=右对齐 / fill=填充(每天都有活动)
- activity_priorities 活动关联优先级(有序,越靠前越重要):
  avoid_similar=避免雷同 / cluster_theme=同主题聚集 / food_balance=饮食均衡
- buffer_min 景点间留白分钟数;max_wait_min 排队/等待时间上限分钟数

规则:用户没提到的字段**不要输出**;只输出 JSON,不要代码块。

用户原话:「{text}」
"""

_PARSE_PROMPT = """你是多人旅行行程规划助手。把一段中文自然语言「旅行偏好」解析为结构化结果,只输出 JSON。

输出格式(JSON):
{{"refuse": ["<POI id>"], "must": ["<POI id>"], "want": ["<POI id>"], "ok": ["<POI id>"]}}

分级定义:
- refuse:明确不接受(不想去/过敏/怕)
- must:必去、非去不可
- want:想去、期待
- ok:可以接受、顺路可去

规则:
1. 只能使用下面提供的 POI id,一个都别发明。
2. 用户明确提到地点就映射到对应 id;提到类目(如「美食」「逛展」)就匹配 tags。
3. 没有提到的不要放进来。

可用 POI 列表:
{poi_hint}


用户偏好:「{text}」
"""


_ASSESS_PROMPT = """【软偏好达成度核对】你是旅行行程核对助手。下面给出一份**已定稿**的行程,以及每位成员声明的软偏好标签。
请判断每位成员的每条软偏好,在这份行程里是**被照顾到了**(satisfied)、**没被照顾到**(missed),
还是**被直接违反**(violated)。

输出格式(JSON,**键是成员的 idx 整数**):
{{"0": {{"satisfied": ["<标签id>"], "missed": ["<标签id>"], "violated": ["<标签id>"]}}, "1": {{...}}}}

判断规则:
1. 只能使用下面列出的标签 id,一个都别发明。
2. **只评估该成员自己声明过的标签**,不要替别人加戏。
3. satisfied = 行程的安排确实体现了这条偏好(如「轻松为主」而每天只排 2-3 个点、步行少);
   missed = 看不出体现,或与偏好相冲突但不算严重;
   violated = 行程**明确做了这名成员接受不了的事**(如声明「不吃辣」却排了麻辣火锅)。
   判断 violated 请只看**语义**,不要看这名成员把它填在「一定要」还是「避免」那一栏 ——
   填在哪一栏不影响它算不算被违反。
4. 判断不了就放进 missed,**不要瞎猜 satisfied**。
5. **每条标签都要有归属**:该成员声明的每一条,必须出现在 satisfied / missed / violated
   三者之一。一条都不能漏,也不要同一标签放进两个列表。
6. 输出 JSON,不要代码块。

可选标签:
{tag_hint}

待核对的数据(参与者 + 行程):
{payload}
"""


def _loads(content: str) -> dict:
    """容错解析模型输出:可能夹带前后缀说明或 ```json 代码块。

    返回 {} 表示解析失败,由调用方决定是降级还是报错。
    """
    for candidate in (content, content.strip().strip("`")):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    # 退一步:截取第一个 { 到最后一个 } 之间的片段
    start, end = content.find("{"), content.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(content[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return {}


class DeepSeekProvider(LLMProvider):
    """OpenAI 兼容客户端。base_url / model / key 均在构造时从环境变量读取。"""

    name = "llm"
    # 类级默认:测试里常用 `__new__` 绕过 __init__,没有它 assess_soft 会 AttributeError
    _assess_timeout: float = 20.0

    def __init__(self) -> None:
        key = _env("LLM_API_KEY", "DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("未设置 LLM_API_KEY(或 DEEPSEEK_API_KEY)")
        base = _env("LLM_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.deepseek.com")
        self._model = _env("LLM_MODEL", "DEEPSEEK_MODEL", default="deepseek-chat")
        # 软偏好自评的**单独**超时:行程这时已经合法,不能让一次慢调用把它拖住。
        # 20s 是按快模型(约 1s)定的;DeepSeek 上同规模载荷要 ~39s,
        # 超时后 `assess_soft` 会**静默降级为「未评估」**,公平页整列变空 —— 症状是
        # "软偏好怎么全没了"而不是任何报错。换慢模型就必须同时调大这个值。
        self._assess_timeout = _env_float("LLM_ASSESS_TIMEOUT", default=20.0)
        self._client = httpx.Client(
            base_url=base.rstrip("/"), timeout=httpx.Timeout(180.0, connect=15.0),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )

    def _chat(self, messages: list[dict], temperature: float = 0.2,
              timeout: float | None = None) -> str:
        resp = self._client.post(
            "/chat/completions",
            json={"model": self._model, "messages": messages, "temperature": temperature,
                  "response_format": {"type": "json_object"}},
            timeout=timeout,
        )
        if resp.status_code == 401:
            raise ProviderError("AI 服务鉴权失败,请联系管理员检查密钥配置")
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def parse_text(self, text: str, pois: list[POI]) -> StructuredPref:
        from ..scheduler.tiers import sanitize_pref

        hint = "\n".join(
            f"- {p.id}:{p.name}(别名:{','.join(p.aliases)};tags:{','.join(p.tags)})" for p in pois
        )
        content = self._chat([{"role": "user", "content": _PARSE_PROMPT.format(poi_hint=hint, text=text)}])
        payload = _loads(content)
        if not payload:
            raise ProviderError("AI 返回的内容无法解析为偏好(格式异常),请重试或换一种说法")
        try:
            return sanitize_pref(StructuredPref.model_validate(payload))
        except Exception as e:
            # 不要把 pydantic 的校验报错原文抛给用户(是开发细节);原始异常仍由 from e 保留在日志里
            raise ProviderError("AI 返回的偏好内容格式不对,请重试或换一种说法") from e

    def explain(self, trace: dict) -> str:
        content = self._chat([
            {"role": "system", "content": "你是一位温和、口吻像朋友的旅行规划师,一句话讲清楚行程取舍,50字内。"},
            {"role": "user", "content": json.dumps(trace, ensure_ascii=False)},
        ], temperature=0.7)
        return content.strip().strip('"')

    # ---------------- AI-harness:大模型编排行程 ----------------
    def draft_itinerary(self, trip, pois: "dict[str, POI]", context: str) -> str:
        content = self._chat([
            {"role": "system", "content":
             "你是资深旅行规划师。根据上下文里的参与者偏好,排一份可执行的多日行程。"
             "硬规则:只使用给定 POI id;refuse 绝不能出现;每位成员的 must 全部纳入;"
             "景点必须在自己的开放时间内、且当天 09:00-21:00 内;总花费(门票+打车)不超预算。"
             "严格只输出 JSON(不要代码块):{\"days\":[{\"day\":0,\"stops\":[\"poi_id\", ...]}, ...]}"},
            {"role": "user", "content": context},
        ], temperature=0.3)
        return content

    def revise_itinerary(self, draft: str, issues: str, context: str = "") -> str:
        """修正草案。**必须带上原始上下文**,否则模型不知道哪些 id 合法,
        只会把「未知地点」的错反复重犯。
        """
        user = f"原始请求与可用景点清单:\n{context}\n\n你的草案:\n{draft}\n\n守门校验发现的问题:\n{issues}" if context \
            else f"草案:{draft}\n问题:\n{issues}"
        content = self._chat([
            {"role": "system", "content":
             "下面是你的行程草案和守门校验列出的问题。请修正后严格只输出修正版 JSON"
             "(不要代码块,不要解释):{\"days\":[{\"day\":0,\"stops\":[\"poi_id\", ...]}, ...]}。"
             "注意:poi_id 必须从上面清单里**逐字复制**(形如 sh12),严禁自己编造英文名或改写。"},
            {"role": "user", "content": user},
        ], temperature=0.2)
        return content

    # ---------------- 扩展软偏好 / 全局推荐设置 ----------------
    def parse_soft_prefs(self, text: str, vocab: list) -> "TagPref":
        """软偏好是**次要**信息:解析失败不应阻塞成员创建,故降级为空。"""
        from ..scheduler.tiers import sanitize_tag_pref

        hint = "\n".join(
            f"- {t.id}:{t.label}[{t.category_label}](别名:{','.join(t.aliases)})" for t in vocab
        )
        try:
            content = self._chat([{"role": "user", "content": _SOFT_PROMPT.format(tag_hint=hint, text=text)}])
            payload = _loads(content)
            if not payload:
                return TagPref()
            ids = {t.id for t in vocab}
            filtered = {k: [x for x in v if x in ids] for k, v in payload.items() if k in ("refuse", "must", "want", "ok")}
            return sanitize_tag_pref(TagPref.model_validate(filtered))
        except Exception:
            return TagPref()

    def parse_reco_settings(self, text: str) -> "RecoSettings":
        content = self._chat([{"role": "user", "content": _SETTINGS_PROMPT.format(text=text)}])
        payload = _loads(content)
        if not payload:
            raise ProviderError("AI 返回的设置无法解析(格式异常),请重试")
        # 未知枚举值一律丢弃,回落默认,避免污染 RecoSettings
        allowed = {
            "conflict_strategy": {"rotate", "split", "majority"},
            "schedule_align": {"left", "center", "right", "fill"},
        }
        for k, ok in allowed.items():
            if payload.get(k) not in ok:
                payload.pop(k, None)
        payload.pop("raw_text", None)
        try:
            return RecoSettings.model_validate(payload)
        except Exception as e:
            raise ProviderError("AI 返回的设置内容格式不对,请重试") from e

    # ---------------- 软偏好自评(定稿后) ----------------
    def assess_soft(self, trip, stops_by_day: dict, vocab: list) -> dict:
        """核对软偏好达成度。**永不抛错** —— 自评失败只降级为"未评估"。

        成员用**位置整数索引**作键:成员 id 是 6 位 hex,模型有编造/改写 id 的前科
        (决策宪法 1.1 就是为它加的);名字会重名。整数拼不错、与顺序无关、越界即丢。
        """
        from ..scheduler.fairness import normalize_soft

        label_of = {t.id: t.label for t in vocab}
        vocab_ids = {t.id for t in vocab}

        payload_people: list[dict] = []
        needed: set[str] = set()
        for idx, p in enumerate(trip.participants):
            soft = {lv: list(getattr(p.soft, lv)) for lv in ("refuse", "must", "want", "ok")}
            soft = {lv: ids for lv, ids in soft.items() if ids}
            needed |= {t for ids in soft.values() for t in ids}
            payload_people.append({"idx": idx, "name": p.name, "soft": soft})
        if not needed:  # 没人声明软偏好 —— 不必打扰模型
            return {}

        itinerary = [
            {
                "day": day,
                "stops": [
                    {"name": s.name, "start": f"{s.start_min // 60:02d}:{s.start_min % 60:02d}",
                     "end": f"{s.end_min // 60:02d}:{s.end_min % 60:02d}",
                     "travel_min": s.travel_min, "tags": s.tags}
                    for s in stops_by_day.get(day, [])
                ],
            }
            for day in sorted(stops_by_day) if stops_by_day.get(day)
        ]

        tag_hint = "\n".join(f"- {t}:{label_of[t]}" for t in sorted(needed) if t in label_of)
        body = json.dumps({"participants": payload_people, "itinerary": itinerary}, ensure_ascii=False)
        base = _ASSESS_PROMPT.format(tag_hint=tag_hint, payload=body)

        def ask(extra: str | None = None) -> dict:
            msgs = [{"role": "user", "content": base}]
            if extra:
                msgs.append({"role": "user", "content": extra})
            content = self._chat(msgs, temperature=0.2, timeout=self._assess_timeout)
            return normalize_soft(_loads(content), trip.participants, vocab_ids)

        try:
            # 自评是**锦上添花**:行程这时已经合法了,绝不能让一次慢调用把它拖垮。
            # 客户端默认超时 180s,这里收紧到 `LLM_ASSESS_TIMEOUT`(默认 20s)。
            # ⚠️ 换慢模型(如 DeepSeek,同规模 ~39s)必须调大,否则整列静默变「未评估」。
            out = ask()
            # 模型漏答某条已声明标签时,要求它**重新输出完整 JSON**(而不是只补漏的那几条)
            # —— 补丁式回答会让先前答对的标签在重新归一化时反而变成"未评估"。
            # 这与草案的 revise 同款:把失败清单回喂,而不是在本地替模型猜一个裁决。
            gaps = [f"{p.name}:{','.join(out[p.id]['unaccounted'])}"
                    for p in trip.participants if out.get(p.id, {}).get("unaccounted")]
            if gaps:
                out = ask("你上一条回答漏掉了这些标签:" + ";".join(gaps)
                          + "。请**重新输出完整的 JSON**,该成员声明的每一条都要有归属。")
            return out
        except Exception:
            return {}
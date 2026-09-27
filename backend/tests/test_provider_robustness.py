"""AI 提供方健壮性 —— 真模型返回异常输出时的行为(不 500、不静默错乱)。

用假 key + 拦截 _chat 驱动 DeepSeek 路径,验证「除 API key 外链路已完备」。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.ai import deepseek_provider as ds
from app.ai.provider import reset_provider
from app.errors import ProviderError
from app.main import app


@pytest.fixture
def dsc(monkeypatch):
    """返回一个已注入假 key 的 DeepSeekProvider(跳过 __init__ 的网络依赖)。"""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    reset_provider()
    yield ds.DeepSeekProvider.__new__(ds.DeepSeekProvider)
    reset_provider()


def _set_chat(monkeypatch, fn):
    monkeypatch.setattr(ds.DeepSeekProvider, "_chat", fn)


# ---------------------------------------------------------------- 容错解析
def test_loads_handles_code_fence_and_noise():
    assert ds._loads('{"a":1}') == {"a": 1}
    assert ds._loads('```json\n{"a":1}\n```') == {"a": 1}
    assert ds._loads('好的,结果:{"a":1} 希望有帮助') == {"a": 1}
    assert ds._loads("完全不是 JSON") == {}
    assert ds._loads("") == {}


def test_parse_text_raises_readable_on_garbage(dsc, monkeypatch):
    _set_chat(monkeypatch, lambda self, m, temperature=0.2: "我不是 JSON")
    from app.data.loader import load_city

    with pytest.raises(ProviderError) as ei:
        dsc.parse_text("x", load_city("shanghai"))
    assert "重试" in ei.value.message


def test_parse_soft_prefs_degrades_silently(dsc, monkeypatch):
    """软偏好是次要信息 —— 解析失败应返回空,而不是抛错阻塞成员创建。"""
    from app.data.loader import vocab_tags

    _set_chat(monkeypatch, lambda self, m, temperature=0.2: "炸了")
    pref = dsc.parse_soft_prefs("x", vocab_tags())
    assert pref.model_dump() == {"refuse": [], "must": [], "want": [], "ok": []}


def test_parse_soft_prefs_filters_unknown_tag_ids(dsc, monkeypatch):
    """模型编造的 tag id 必须被丢弃,不能污染偏好。"""
    from app.data.loader import vocab_tags

    _set_chat(monkeypatch, lambda self, m, temperature=0.2:
              json.dumps({"must": ["en_light", "不存在的标签"], "want": [], "refuse": [], "ok": []}))
    pref = dsc.parse_soft_prefs("x", vocab_tags())
    assert pref.must == ["en_light"]


def test_parse_reco_settings_drops_unknown_enum(dsc, monkeypatch):
    """枚举值不在白名单内 → 丢弃回落默认,不污染设置。"""
    _set_chat(monkeypatch, lambda self, m, temperature=0.2:
              json.dumps({"conflict_strategy": "随便写的", "schedule_align": "left", "buffer_min": 20}))
    s = dsc.parse_reco_settings("x")
    assert s.conflict_strategy == "rotate"     # 回落默认
    assert s.schedule_align == "left"          # 合法值保留
    assert s.buffer_min == 20


def test_draft_itinerary_bad_output_reaches_validator(dsc, monkeypatch):
    """草案非法 JSON 不抛错,交给守门层判定为空草案(最终 422,而非 500)。"""
    from app.data.loader import pois_by_id

    monkeypatch.setattr(ds.DeepSeekProvider, "_chat", lambda self, m, temperature=0.3: "不是 JSON")
    from app.scheduler.harness import _parse_draft

    assert _parse_draft(dsc.draft_itinerary(None, pois_by_id("shanghai"), "行程规划请求")) == {}


# ---------------------------------------------------------------- 端到端(假 LLM)
def test_full_pipeline_with_dsl_provider(monkeypatch):
    """假 key + 假响应,跑通「输入 → 景点意愿 / 软偏好 / 全局设置 → 生成行程」。"""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    reset_provider()

    draft = {"days": [{"day": 0, "stops": ["sh09", "sh05"]}, {"day": 1, "stops": ["sh07"]}]}
    hits: list[str] = []

    def fake(self, messages, temperature=0.2, timeout=None):
        text = " ".join(m.get("content", "") for m in messages)
        if "行程草案" in text or "修正版" in text:
            hits.append("draft")
            return json.dumps(draft)
        if "行程规划请求" in text:
            hits.append("draft")
            return json.dumps(draft)
        if "模糊软偏好" in text:
            hits.append("soft")
            return json.dumps({"must": ["en_light"], "want": [], "refuse": [], "ok": []})
        if "全局推荐设置" in text:
            hits.append("settings")
            return json.dumps({"conflict_strategy": "split", "schedule_align": "left", "buffer_min": 20})
        # ★ 自评必须**先于**兜底分支判定。否则这个调用会落进最后的偏好兜底,
        # 返回一个没有整数键的偏好结构 → normalize_soft 丢光 → soft_cared 恒为 0,
        # 测试仍然"通过",而 assess_soft 的解析链路一次都没跑到。
        if "软偏好达成度" in text:
            hits.append("assess")
            assert timeout == 20.0, "自评必须走收紧后的超时,不能拖 180s 默认值"
            return json.dumps({"0": {"satisfied": ["en_light"], "missed": [], "violated": []}})
        hits.append("fallback")
        return json.dumps({"refuse": ["sh12"], "must": ["sh09"], "want": [], "ok": ["sh21"]})

    monkeypatch.setattr(ds.DeepSeekProvider, "_chat", fake)

    c = TestClient(app)
    tid = c.post("/api/trip", json={"city": "shanghai", "days": 2, "total_budget": 1500}).json()["id"]

    r = c.post(f"/api/trip/{tid}/participants", json={"name": "球球", "natural_text": "随便一句"})
    assert r.status_code == 200
    p = r.json()["participants"][0]
    assert p["pref"]["must"] == ["sh09"]          # 景点意愿
    assert p["soft"]["must"] == ["en_light"]      # 软偏好

    r = c.patch(f"/api/trip/{tid}/settings", json={"natural_text": "随便一句"})
    assert r.status_code == 200
    assert r.json()["settings"]["conflict_strategy"] == "split"
    assert r.json()["settings"]["buffer_min"] == 20

    r = c.post(f"/api/trip/{tid}/plan")
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["engine"] == "ai"
    assert {s["poi_id"] for d in plan["days"] for s in d["stops"]} >= {"sh09"}
    assert all(x["must_met"] == x["must_total"] for x in plan["fairness"]["participants"])

    # 自评确实跑过,且结果流进了公平报告(而不是被静默降级成"未评估")
    assert "assess" in hits
    row = plan["fairness"]["participants"][0]
    assert row["soft_declared"] == 1
    assert row["soft_cared"] == 1
    assert row["soft_rate"] == 1.0
    assert row["soft_satisfied"] == ["en_light"]

    reset_provider()


def test_assess_soft_reports_unaccounted_instead_of_silently_dropping(dsc, monkeypatch):
    """★ 回归护栏:模型漏答某条已声明标签时,不能静默丢弃、也不能算成 0%。

    实测(真实模型,2026-09-27):成员声明了「不吃辣」,AI 排了两个美食点后返回
    `violated=[] missed=[]` —— 这个标签**整个被漏掉**。旧实现下 `soft_cared=0`,
    页面显示「未评估」,于是一个明确声明过的饮食禁忌变成什么都不显示。

    正确行为:该标签落 `unaccounted`,并由 summarize 如实报出。
    """
    import uuid

    from app.data.loader import vocab_tags
    from app.models import Participant, StructuredPref, TagPref
    from app.scheduler.fairness import build_fairness_report

    p = Participant(id=uuid.uuid4().hex[:6], name="球球",
                    pref=StructuredPref(must=["sh02"]), soft=TagPref(refuse=["di_mild"]))
    trip = type("T", (), {"participants": [p]})()

    calls = []
    # 模型两次都只回空对象(第一次漏答 → 触发补问 → 补问仍漏答)
    _set_chat(monkeypatch, lambda self, m, temperature=0.2, timeout=None:
              calls.append(m) or "{}")
    out = dsc.assess_soft(trip, {}, vocab_tags())
    assert out[p.id]["unaccounted"] == ["di_mild"]
    assert len(calls) == 2, "漏答必须触发一次补问(与草案的 revise 同款)"

    report = build_fairness_report([p], {0: []}, [], soft_rows=out, valid_ids={"sh02"})
    row = report.participants[0]
    assert row.soft_declared == 1        # refuse 层也要计入声明数
    assert row.soft_cared == 0
    assert row.soft_rate is None         # 未评估,绝不是 0%
    assert any("未获评估" in m for m in report.summary_messages)


def test_assess_soft_completes_after_one_repair_round(dsc, monkeypatch):
    """第一次漏答 → 补问后补齐 → 采用补齐的结果(且不残留 unaccounted)。"""
    import uuid

    from app.data.loader import vocab_tags
    from app.models import Participant, StructuredPref, TagPref

    p = Participant(id=uuid.uuid4().hex[:6], name="球球",
                    pref=StructuredPref(must=["sh02"]), soft=TagPref(refuse=["di_mild"]))
    trip = type("T", (), {"participants": [p]})()

    replies = iter(["{}", json.dumps({"0": {"violated": ["di_mild"]}})])
    _set_chat(monkeypatch, lambda self, m, temperature=0.2, timeout=None: next(replies))
    out = dsc.assess_soft(trip, {}, vocab_tags())
    assert out[p.id]["violated"] == ["di_mild"]
    assert out[p.id]["unaccounted"] == []


def test_assess_soft_returns_empty_when_call_itself_fails(dsc, monkeypatch):
    """调用直接抛错 → `{}`(真正的「未评估」),绝不抛给上层、也不算 0%。

    行程此时已经合法了,一次失败的自评不能把整个生成流程拖垮。
    """
    import uuid

    from app.data.loader import vocab_tags
    from app.models import Participant, StructuredPref, TagPref

    p = Participant(id=uuid.uuid4().hex[:6], name="甲",
                    pref=StructuredPref(must=["sh02"]), soft=TagPref(must=["en_light"]))
    trip = type("T", (), {"participants": [p]})()

    def boom(self, m, temperature=0.2, timeout=None):
        raise RuntimeError("网关 502")

    _set_chat(monkeypatch, boom)
    assert dsc.assess_soft(trip, {}, vocab_tags()) == {}


def test_assess_soft_skips_model_when_nobody_declared(dsc, monkeypatch):
    """没人声明软偏好时不该打扰模型(省一次调用,也省 20s 潜在延迟)。"""
    from app.data.loader import vocab_tags

    called = []
    _set_chat(monkeypatch, lambda self, m, temperature=0.2, timeout=None:
              called.append(1) or "{}")

    import uuid

    from app.models import Participant, StructuredPref

    p = Participant(id=uuid.uuid4().hex[:6], name="甲", pref=StructuredPref(must=["sh02"]))
    trip = type("T", (), {"participants": [p]})()
    assert dsc.assess_soft(trip, {}, vocab_tags()) == {}
    assert called == []


# ------------------------------------------------- 自评超时(静默失败,必须可调)
def test_env_float_parses_and_survives_garbage(monkeypatch):
    """写坏了/写负了都退回默认值 —— 一个笔误不该让服务起不来。"""
    monkeypatch.setenv("PROBE_T", "45")
    assert ds._env_float("PROBE_T", 20.0) == 45.0

    monkeypatch.setenv("PROBE_T", "  7.5  ")
    assert ds._env_float("PROBE_T", 20.0) == 7.5

    for bad in ("", "   ", "abc", "0", "-3"):
        monkeypatch.setenv("PROBE_T", bad)
        assert ds._env_float("PROBE_T", 20.0) == 20.0, f"{bad!r} 应退回默认值"

    monkeypatch.delenv("PROBE_T")
    assert ds._env_float("PROBE_T", 20.0) == 20.0


def test_assess_soft_honours_configurable_timeout(monkeypatch):
    """自评超时必须走 `LLM_ASSESS_TIMEOUT`,不能是写死的常数。

    真实踩过的坑:20s 是按快模型(~1s)定的,换到 DeepSeek(同规模 ~39s)后
    **静默**超时 —— 不报错,只是公平页软偏好整列变成「未评估」。写死的常数没法治,
    可配置才能治;这条用例就是防止它再被写死回去。
    """
    import uuid

    from app.data.loader import vocab_tags
    from app.models import Participant, StructuredPref, TagPref

    monkeypatch.setenv("LLM_ASSESS_TIMEOUT", "90")
    monkeypatch.setenv("LLM_API_KEY", "test-key")  # 让 __init__ 能过 key 检查
    p = ds.DeepSeekProvider()
    assert p._assess_timeout == 90.0

    seen = []
    _set_chat(monkeypatch, lambda self, m, temperature=0.2, timeout=None:
              seen.append(timeout) or "{}")

    person = Participant(id=uuid.uuid4().hex[:6], name="甲",
                         pref=StructuredPref(must=["sh02"]), soft=TagPref(must=["en_light"]))
    trip = type("T", (), {"participants": [person]})()
    p.assess_soft(trip, {}, vocab_tags())

    # 假件回 "{}" → 声明过的标签全部 unaccounted → 会触发**补问一轮**,所以是两次调用。
    # 断言"每一次"都用配置值:真踩过的坑正是这个数被写死,而不是它被用了几次。
    # ⚠️ 顺带记住:慢模型上补问一轮 = 自评延迟翻倍(DeepSeek 实测 39s → 最坏约 78s)。
    assert seen and set(seen) == {90.0}, f"传给 _chat 的超时应都是配置值,实际 {seen}"


def test_assess_timeout_default_is_class_level():
    """`__new__` 绕开 __init__ 的实例也要能用(测试替身就是这么造的)。"""
    assert isinstance(ds.DeepSeekProvider._assess_timeout, float)


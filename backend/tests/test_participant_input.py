"""成员输入历史 —— 「原始输入 + 每次补充」的记录与展示(API 层)。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _trip() -> str:
    c = TestClient(app)
    return c.post("/api/trip", json={"city": "shanghai", "days": 2, "total_budget": 1500}).json()["id"]


def test_nl_input_recorded_in_history():
    """自然语言添加成员 → 原文进入历史。"""
    c = TestClient(app)
    tid = _trip()
    r = c.post(f"/api/trip/{tid}/participants",
               json={"name": "小林", "natural_text": "我超想去上海天文馆,喜欢美食"})
    p = r.json()["participants"][0]
    assert p["natural_inputs"] == ["我超想去上海天文馆,喜欢美食"]
    assert p["natural_text"] == "我超想去上海天文馆,喜欢美食"


def test_merge_appends_history():
    """「再补充几句」→ 追加,不覆盖原始输入。"""
    c = TestClient(app)
    tid = _trip()
    c.post(f"/api/trip/{tid}/participants", json={"name": "小林", "natural_text": "想去天文馆"})
    r = c.post(f"/api/trip/{tid}/participants",
               json={"name": "小林", "natural_text": "怕累不想走太多", "merge": True})
    p = r.json()["participants"][0]
    assert p["natural_inputs"] == ["想去天文馆", "怕累不想走太多"]
    assert p["natural_text"] == "想去天文馆；怕累不想走太多"


def test_already_parsed_records_without_reparsing():
    """两步解析流程:前端已解析,后端只记原文,且 structured/soft 生效。

    这是「输入历史为空」那个 bug 的回归 —— 前端传 already_parsed 时,
    原文仍必须进历史。
    """
    c = TestClient(app)
    tid = _trip()
    r = c.post(f"/api/trip/{tid}/participants", json={
        "name": "小林",
        "natural_text": "我超想去上海天文馆",
        "structured": {"refuse": [], "must": ["sh02"], "want": [], "ok": []},
        "soft": {"refuse": [], "must": ["en_light"], "want": [], "ok": []},
        "already_parsed": True,
    })
    p = r.json()["participants"][0]
    assert p["natural_inputs"] == ["我超想去上海天文馆"]      # 原文被记录
    assert p["pref"]["must"] == ["sh02"]                       # 用前端给的结构化结果
    assert p["soft"]["must"] == ["en_light"]


def test_structured_only_keeps_history_empty():
    """纯榜单点选(无自然语言)→ 历史为空,但没有报错。"""
    c = TestClient(app)
    tid = _trip()
    r = c.post(f"/api/trip/{tid}/participants",
               json={"name": "小周", "structured": {"must": ["sh12"], "want": [], "refuse": [], "ok": []}})
    p = r.json()["participants"][0]
    assert p["natural_inputs"] == []
    assert p["pref"]["must"] == ["sh12"]


def test_structured_edit_does_not_wipe_history():
    """用榜单增删景点(结构化覆盖)不应清空已有的语言输入历史。"""
    c = TestClient(app)
    tid = _trip()
    c.post(f"/api/trip/{tid}/participants", json={"name": "小林", "natural_text": "想去天文馆"})
    r = c.post(f"/api/trip/{tid}/participants", json={
        "name": "小林",
        "structured": {"refuse": [], "must": ["sh02", "sh05"], "want": [], "ok": []},
    })
    p = r.json()["participants"][0]
    assert p["natural_inputs"] == ["想去天文馆"]   # 历史保留
    assert p["pref"]["must"] == ["sh02", "sh05"]   # 榜单编辑生效

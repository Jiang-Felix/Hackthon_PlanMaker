"""帖子图文段落(行程分享的扩展能力):按地点/按天附照片与文字评论 —— API 级测试。

注意:全局 store 为内存态且**不被 conftest 重置**,故断言尽量用「存在 / 属性」而非全量计数。
社区已移除种子帖,现存帖子必带 trip_id。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

IMG = "data:image/png;base64,iVBORw0KGgo="


def _photos(n: int) -> list[dict]:
    return [{"data": IMG} for _ in range(n)]


def test_community_starts_without_seed_posts():
    c = TestClient(app)
    posts = c.get("/api/posts").json()
    # 旧种子帖的作者不应出现;现存帖子都带 trip_id —— 内容只来自行程分享
    assert not ({p["author"] for p in posts} & {"阿May", "小林", "球球", "一家三口"})
    assert all(p["trip_id"] for p in posts)


def test_create_post_with_poi_and_day_sections():
    c = TestClient(app)
    r = c.post("/api/posts", json={
        "city": "shanghai",
        "trip_id": "t1",
        "sections": [
            {"kind": "poi", "poi_id": "sh01", "title": "外滩", "subtitle": "10:00-12:00",
             "note": "江风很大", "photos": _photos(1)},
            {"kind": "day", "day": 1, "title": "第 2 天", "subtitle": "9/28 周日",
             "note": "", "photos": _photos(2)},
        ],
    }).json()
    assert r["text"] == ""                       # 纯图文帖(无正文)也允许
    assert r["trip_id"] == "t1"

    s0, s1 = r["sections"]
    assert s0["kind"] == "poi" and s0["poi_id"] == "sh01" and s0["note"] == "江风很大"
    assert s0["photos"][0]["id"]                 # store 补上了 photo id
    assert s0["photos"][0]["data"] == IMG        # data 原样往返
    assert s1["day"] == 1 and len(s1["photos"]) == 2

    # 最新在前
    assert c.get("/api/posts").json()[0]["id"] == r["id"]


def test_post_create_without_trip_id_is_rejected():
    """内容只来自行程分享 → 缺 trip_id 必须 422(空串同样拒绝)。"""
    c = TestClient(app)
    assert c.post("/api/posts", json={"city": "shanghai", "text": "没有行程"}).status_code == 422
    assert c.post("/api/posts", json={"city": "shanghai", "trip_id": "", "text": "x"}).status_code == 422


def test_sections_survive_like_and_comment():
    """点赞/评论走的是 {**post.model_dump(), comments} 合并 —— 段落与照片不能丢。"""
    c = TestClient(app)
    r = c.post("/api/posts", json={
        "city": "shanghai", "trip_id": "t2",
        "sections": [{"kind": "day", "day": 0, "title": "第 1 天", "photos": _photos(1)}],
    }).json()
    c.post(f"/api/posts/{r['id']}/like")
    c.post(f"/api/posts/{r['id']}/comments", json={"text": "好看!"})

    target = next(x for x in c.get("/api/posts").json() if x["id"] == r["id"])
    assert len(target["sections"]) == 1 and target["sections"][0]["photos"][0]["data"] == IMG
    assert any(cm["text"] == "好看!" for cm in target["comments"])


def test_post_validation_rejects_bad_payloads():
    c = TestClient(app)
    cases = [
        ("空帖", {"city": "shanghai", "trip_id": "t", "text": ""}),
        ("非 data URL", {"city": "shanghai", "trip_id": "t",
                         "sections": [{"kind": "poi", "poi_id": "sh01",
                                       "photos": [{"data": "http://x/y.jpg"}]}]}),
        ("day 段缺 day", {"city": "shanghai", "trip_id": "t", "sections": [{"kind": "day", "day": None}]}),
        ("poi 段缺 poi_id", {"city": "shanghai", "trip_id": "t", "sections": [{"kind": "poi", "poi_id": ""}]}),
        ("非法 kind", {"city": "shanghai", "trip_id": "t", "sections": [{"kind": "photo"}]}),
        ("单段 5 张", {"city": "shanghai", "trip_id": "t",
                       "sections": [{"kind": "day", "day": 0, "photos": _photos(5)}]}),
        ("全帖 10 张", {"city": "shanghai", "trip_id": "t", "sections": [
            {"kind": "day", "day": 0, "photos": _photos(4)},
            {"kind": "day", "day": 1, "photos": _photos(4)},
            {"kind": "day", "day": 2, "photos": _photos(2)}]}),
        ("正文超长", {"city": "shanghai", "trip_id": "t", "text": "x" * 2001}),
        ("段落过多", {"city": "shanghai", "trip_id": "t",
                      "sections": [{"kind": "day", "day": 0}] * 13}),
    ]
    for label, payload in cases:
        assert c.post("/api/posts", json=payload).status_code == 422, label


def test_realistic_photo_size_accepted():
    """一张 ~100KB base64 的照片应被接受(护栏:后续别把上限收得过紧)。"""
    c = TestClient(app)
    big = "data:image/jpeg;base64," + "A" * 100_000
    r = c.post("/api/posts", json={
        "city": "shanghai", "trip_id": "t3",
        "sections": [{"kind": "poi", "poi_id": "sh03", "photos": [{"data": big}]}],
    })
    assert r.status_code == 200 and r.json()["sections"][0]["photos"][0]["data"] == big

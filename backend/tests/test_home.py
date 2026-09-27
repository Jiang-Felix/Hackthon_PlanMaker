"""五栏外壳(评审 System Design):管理列表 / 图鉴自动+手动打卡 / 个人资料 / 社区论坛 —— 内存态 API 测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import DayPlan, DayStop, PlanResult, TripState
from app.store import store


def _started_trip_with_plan():
    """30h 前出发的两天行程 + 一份 day0=[sh12], day1=[sh02] 的计划。

    按墙钟 current_day 自动算=1(day0 已冻结),于是自动打卡只记 sh12。
    """
    start_at = (datetime.now() - timedelta(hours=30)).isoformat(timespec="minutes")

    def stop(pid: str) -> DayStop:
        return DayStop(poi_id=pid, name=pid, start_min=600, end_min=720, arrive_min=600,
                       travel_min=0, price=0, tags=[])

    trip = TripState(id="", city="shanghai", days=2, total_budget=1000,
                     hotel_lat=31.23, hotel_lng=121.47, start_at=start_at)
    trip.current_plan = PlanResult(city="shanghai", days=[
        DayPlan(day=0, stops=[stop("sh12")], day_spent=0),
        DayPlan(day=1, stops=[stop("sh02")], day_spent=0),
    ], total_budget=1000)
    return store.create(trip)


def test_trips_listing_reverse_and_delete():
    c = TestClient(app)
    t0 = c.post("/api/trip", json={"city": "shanghai", "days": 2, "total_budget": 1200,
                                   "start_at": "2026-09-27T09:00"}).json()
    t1 = c.post("/api/trip", json={"city": "hangzhou", "days": 3, "total_budget": 2000,
                                   "start_at": "2099-01-01T09:00"}).json()
    trips = c.get("/api/trips").json()
    # 全局 store 可能被其它测试留下更早的行程 —— 只断言「刚建的两个排在最前且倒序」
    assert [t["id"] for t in trips[:2]] == [t1["id"], t0["id"]]
    assert trips[0]["city"] == "hangzhou" and trips[0]["created_at"]
    c.delete(f'/api/trip/{t1["id"]}')
    ids = [t["id"] for t in c.get("/api/trips").json()]
    assert t1["id"] not in ids and t0["id"] in ids
    c.delete(f'/api/trip/{t0["id"]}')
    assert t0["id"] not in [t["id"] for t in c.get("/api/trips").json()]


def test_auto_checkin_from_frozen_days_is_idempotent():
    """★ 图鉴自动打卡:已开始行程的冻结天 → POI 自动进图鉴;重复 sweep 不重复计数。"""
    trip = _started_trip_with_plan()
    now = datetime.now()

    added = store.sweep_checkins(now)
    assert added >= 1
    rec = store.collection().get("sh12")
    assert rec is not None and rec.city == "shanghai" and rec.count >= 1
    n_after = store.collection()["sh12"].count
    # 幂等:再 sweep 一次 count 不再涨
    assert store.sweep_checkins(now) == 0
    assert store.collection()["sh12"].count == n_after
    # 未冻结的天(day1 的 sh02)不该自动打卡
    assert store.collection().get("sh02") is None

    # 反馈到 API:图鉴里有 sh12,且上海进度至少 1/25
    data = c = None
    c = TestClient(app)
    data = c.get("/api/collection").json()
    assert any(r["poi_id"] == "sh12" for r in data["records"])
    assert data["progress"]["shanghai"]["visited"] >= 1
    assert data["progress"]["shanghai"]["total"] == 25


def test_manual_toggle_collection():
    c = TestClient(app)
    assert c.post("/api/collection/sh15", json={"visited": True}).json()["count"] == 1
    assert c.post("/api/collection/sh15", json={"visited": False}).json()["count"] == 0
    assert c.post("/api/collection/nope", json={"visited": True}).status_code == 404


def test_collection_progress_retreats_after_uncheck():
    """★ 回归护栏:手动取消打卡后,「已点亮 X/Y」的进度必须回退。

    旧实现 visited 把 count==0 的记录也算进去 → 进度只增不减。
    """
    c = TestClient(app)
    c.post("/api/collection/sh16", json={"visited": True})
    before = c.get("/api/collection").json()["progress"]["shanghai"]["visited"]
    c.post("/api/collection/sh16", json={"visited": False})
    after = c.get("/api/collection").json()["progress"]["shanghai"]["visited"]
    assert after == before - 1


def test_profile_get_patch():
    c = TestClient(app)
    c.patch("/api/profile", json={"name": "新昵称", "avatar": "🐯", "bio": "爱玩"})
    p = c.get("/api/profile").json()
    assert p["name"] == "新昵称" and p["avatar"] == "🐯" and p["bio"] == "爱玩"


def test_posts_start_empty_and_crud():
    """社区初始为空(种子演示帖已移除):内容只可能来自行程分享;建帖→点赞→评论闭环。"""
    c = TestClient(app)
    posts = c.get("/api/posts").json()
    # 旧种子帖的作者不应出现;且现存帖子都带 trip_id(新端点强制) —— 两者共同证明无种子残留
    assert not ({p["author"] for p in posts} & {"阿May", "小林", "球球", "一家三口"})
    assert all(p["trip_id"] for p in posts)

    r = c.post("/api/posts", json={"city": "shanghai", "trip_id": "trip-x",
                                   "text": "我的第一条分享", "poi_ids": ["sh12", "sh05"]}).json()
    assert r["trip_id"] == "trip-x" and r["poi_ids"] == ["sh12", "sh05"] and r["sections"] == []

    liked = c.post(f"/api/posts/{r['id']}/like").json()
    assert liked["liked"] is True and liked["likes"] == 1

    c.post(f"/api/posts/{r['id']}/comments", json={"text": "不错!"})
    target = next(x for x in c.get("/api/posts").json() if x["id"] == r["id"])
    assert any(cm["text"] == "不错!" for cm in target["comments"])


def test_like_is_toggleable_and_can_only_be_once():
    """★ 回归护栏:点赞可撤回(单用户只能点一次) —— 再点一次取消,计数回落。"""
    c = TestClient(app)
    pid = c.post("/api/posts", json={"city": "shanghai", "trip_id": "trip-like",
                                     "text": "点赞测试"}).json()["id"]

    a = c.post(f"/api/posts/{pid}/like").json()
    assert a["liked"] is True and a["likes"] == 1
    b = c.post(f"/api/posts/{pid}/like").json()
    assert b["liked"] is False and b["likes"] == 0


def _finished_trip(days: int, poi_per_day: list[str]) -> TripState:
    """早就出发、如今已完全结束的行程(每天计划一处 POI),用于验证「行程结束后」的自动打卡。"""

    def stop(pid: str) -> DayStop:
        return DayStop(poi_id=pid, name=pid, start_min=600, end_min=720, arrive_min=600,
                       travel_min=0, price=0, tags=[])

    start_at = (datetime.now() - timedelta(days=days + 3)).isoformat(timespec="minutes")
    trip = TripState(id="", city="shanghai", days=days, total_budget=1000,
                     hotel_lat=31.23, hotel_lng=121.47, start_at=start_at)
    trip.current_plan = PlanResult(city="shanghai", days=[
        DayPlan(day=i, stops=[stop(p)], day_spent=0) for i, p in enumerate(poi_per_day)
    ], total_budget=1000)
    return store.create(trip)


def test_auto_checkin_covers_final_day_after_trip_ends():
    """★ 回归护栏:行程走完后,**最后一天**的 POI 也必须自动打卡。

    旧实现把冻结上界夹到 days-1,`range(prev, cur)` 永远取不到 index `days-1` ——
    于是多天行程永远漏掉最后一天、单天行程全程不打。
    """
    _finished_trip(2, ["sh20", "sh21"])   # day0=sh20, day1=sh21(避开其它测试占用的 id)
    store.sweep_checkins()
    coll = store.collection()
    assert coll.get("sh20") is not None and coll["sh20"].count >= 1   # 第一天
    assert coll.get("sh21") is not None and coll["sh21"].count >= 1   # 最后一天(旧实现漏掉)

    # 幂等:再 sweep 不重复计数
    before = coll["sh21"].count
    assert store.sweep_checkins() == 0
    assert store.collection()["sh21"].count == before


def test_single_day_trip_auto_checkin():
    """★ 回归护栏:单天行程(days=1)结束后也要自动打卡(旧实现上界恒为 0,永远不打)。"""
    _finished_trip(1, ["sh22"])
    store.sweep_checkins()
    assert store.collection().get("sh22") is not None


def test_trip_initial_people_roundtrip_and_bounds():
    """创建行程可设初始人数(1–8);越界 422;不带该字段时缺省 3(兼容老客户端)。"""
    c = TestClient(app)
    t = c.post("/api/trip", json={"city": "shanghai", "days": 2, "total_budget": 1000,
                                  "initial_people": 5}).json()
    assert t["initial_people"] == 5
    assert c.get(f"/api/trip/{t['id']}").json()["initial_people"] == 5   # 落库可读回
    c.delete(f"/api/trip/{t['id']}")

    d = c.post("/api/trip", json={"city": "shanghai"}).json()
    assert d["initial_people"] == 3
    c.delete(f"/api/trip/{d['id']}")

    assert c.post("/api/trip", json={"city": "shanghai", "initial_people": 0}).status_code == 422
    assert c.post("/api/trip", json={"city": "shanghai", "initial_people": 9}).status_code == 422
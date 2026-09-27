"""内存态行程仓库 —— 单机演示用,不做数据库(评审重心在算法)。

除了行程,还承载五栏外壳的数据:个人资料、图鉴打卡、社区帖子/评论。
全部内容均为内存态,重启即清空(与行程同寿命)。
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime

from .models import CheckInRecord, Comment, Post, PostSection, Profile, TripState


def _now_iso() -> str:
    # 微秒精度:同一秒内创建的多个行程,created_at 也要可比序(「管理」列表排序用)。
    return datetime.now().isoformat(timespec="microseconds")


class TripStore:
    def __init__(self) -> None:
        self._trips: dict[str, TripState] = {}
        self._lock = threading.Lock()
        # 五栏外壳数据
        self._profile = Profile()
        self._collection: dict[str, CheckInRecord] = {}
        self._posts: list[Post] = []
        self._comments: dict[str, list[Comment]] = {}
        self._checked_until: dict[str, int] = {}   # trip_id → 已自动打到的 current_day

    # ------------------------------------------------------------ 行程
    def new_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def create(self, trip: TripState) -> TripState:
        trip.id = self.new_id()
        trip.created_at = _now_iso()
        with self._lock:
            self._trips[trip.id] = trip
        return trip

    def get(self, trip_id: str) -> TripState | None:
        return self._trips.get(trip_id)

    def require(self, trip_id: str) -> TripState:
        trip = self.get(trip_id)
        if trip is None:
            raise KeyError(f"行程不存在: {trip_id}")
        return trip

    def save(self, trip: TripState) -> None:
        with self._lock:
            self._trips[trip.id] = trip

    def all_trips(self, reverse: bool = True) -> list[TripState]:
        return sorted(self._trips.values(), key=lambda t: t.created_at, reverse=reverse)

    def remove(self, trip_id: str) -> None:
        with self._lock:
            if trip_id not in self._trips:
                raise KeyError(trip_id)
            del self._trips[trip_id]
            self._checked_until.pop(trip_id, None)

    # ------------------------------------------------------------ 个人资料
    @property
    def profile(self) -> Profile:
        return self._profile

    def set_profile(self, **kw) -> Profile:
        for k, v in kw.items():
            if v is not None and hasattr(self._profile, k):
                setattr(self._profile, k, v)
        return self._profile

    # ------------------------------------------------------------ 图鉴打卡
    def collection(self) -> dict[str, CheckInRecord]:
        return dict(self._collection)

    def checkin(self, poi_id: str, city: str, now: datetime | None = None) -> CheckInRecord:
        rec = self._collection.get(poi_id)
        if rec is None:
            rec = CheckInRecord(poi_id=poi_id, city=city, count=0)
            self._collection[poi_id] = rec
        rec.count += 1
        if not rec.first_at:
            rec.first_at = (now or datetime.now()).isoformat(timespec="seconds")
        return rec

    def uncheckin(self, poi_id: str) -> None:
        rec = self._collection.get(poi_id)
        if rec is not None:
            rec.count = max(0, rec.count - 1)

    def elapsed_days_for(self, trip: TripState, now: datetime | None = None) -> int:
        """按墙钟算出「已经过的完整天数」:未开始 / 无起点 → 0。**不夹到 days-1**,供冻结判定用。"""
        if not trip.start_at:
            return 0
        now = now or datetime.now()
        try:
            start = datetime.fromisoformat(trip.start_at)
        except ValueError:
            return 0
        if now < start:
            return 0
        return int((now - start).total_seconds() // 86400)

    def current_day_for(self, trip: TripState, now: datetime | None = None) -> int:
        """行程「当前进行到第几天」,夹到 [0, days-1] —— 展示用,与 main._current_day_for 同口径。

        注意:它刻意把「已结束」也压在最后一天(最后一天永远是"今天"),
        所以**冻结判定不能用它**(否则最后一天永远冻不上,见 `sweep_checkins`)。
        """
        return max(0, min(self.elapsed_days_for(trip, now), trip.days - 1))

    def sweep_checkins(self, now: datetime | None = None) -> int:
        """核心联动(幂等):把每个「已开始」行程中**已过完整天**的 POI 自动计入图鉴。

        对每个有 current_plan 的 trip,取真实经过天数(夹到 days),只补
        `[checked_until, 已过天数)` 之间新冻结的天 —— "今天"这一天在过完之前不动。
        返回本次新增打卡数;重复调用不重复计数。
        """
        now = now or datetime.now()
        added = 0
        for trip in self._trips.values():
            if trip.current_plan is None:
                continue
            # 上界夹到 days(而不是 days-1):行程走完后,最后一天也要补上。
            cur = min(self.elapsed_days_for(trip, now), trip.days)
            prev = self._checked_until.get(trip.id, 0)
            if cur <= prev:
                self._checked_until[trip.id] = cur  # 未开始/没推进也保持对齐
                continue
            by_day = {dp.day: dp.stops for dp in trip.current_plan.days}
            for day in range(prev, cur):
                for stop in by_day.get(day, []):
                    self.checkin(stop.poi_id, trip.city, now)
                    added += 1
            self._checked_until[trip.id] = cur
        return added

    # ------------------------------------------------------------ 社区
    def posts(self) -> list[Post]:
        return list(self._posts)

    def add_post(self, author: str, avatar: str, city: str, text: str, poi_ids: list[str],
                 *, trip_id: str = "", sections: list[PostSection] | None = None) -> Post:
        # 深拷贝 + 补 photo id:请求模型与存档不能互相别名。
        cleaned = [s.model_copy(deep=True) for s in (sections or [])]
        for s in cleaned:
            for ph in s.photos:
                ph.id = self.new_id()
        post = Post(
            id=self.new_id(), author=author, avatar=avatar, city=city,
            text=text, created_at=_now_iso(), poi_ids=list(poi_ids),
            trip_id=trip_id, sections=cleaned,
        )
        self._posts.insert(0, post)
        return post

    def toggle_like(self, post_id: str) -> Post | None:
        """点赞/取消点赞(单用户只能点一次):liked=True → 再点取消并减一。"""
        for p in self._posts:
            if p.id == post_id:
                if p.liked:
                    p.likes = max(0, p.likes - 1)
                    p.liked = False
                else:
                    p.likes += 1
                    p.liked = True
                return p
        return None

    def comments(self, post_id: str) -> list[Comment]:
        return list(self._comments.get(post_id, []))

    def add_comment(self, post_id: str, author: str, text: str) -> Comment | None:
        if not any(p.id == post_id for p in self._posts):
            return None
        c = Comment(id=self.new_id(), post_id=post_id, author=author,
                    text=text, created_at=_now_iso())
        self._comments.setdefault(post_id, []).append(c)
        return c


store = TripStore()
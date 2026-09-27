"""FastAPI 入口与 API 路由。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from .ai.provider import get_provider
from .data.loader import (
    available_cities,
    load_city,
    load_preference_vocab,
    vocab_tag_ids,
)
from .models import (
    CheckInRecord,
    Comment,
    Participant,
    ParticipantCreate,
    PlanResult,
    Post,
    PostSection,
    Profile,
    RecoSettings,
    ReplanRequest,
    ReplanResult,
    StructuredPref,
    TagPref,
    TripCreate,
    TripState,
)
from .errors import PlanValidationError, ProviderError
from .scheduler.cost import sync_essentials
from .scheduler.harness import ai_plan
from .scheduler.replan import replan
from .scheduler.tiers import (
    merge_prefs,
    merge_tag_pref,
    sanitize_pref,
    sanitize_tag_pref,
)
from .store import store

app = FastAPI(
    title="行程平衡器 · Trip Balancer",
    description="多人旅行偏好平衡排程 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProviderError)
def _on_provider_error(request, exc: ProviderError):
    """AI 提供方不可用 / 返回异常 → 502,附带可读说明(前端直接展示)。"""
    return JSONResponse(status_code=502, content={"detail": {"message": exc.message}})


@app.exception_handler(PlanValidationError)
def _on_validation_error(request, exc: PlanValidationError):
    """AI 方案不满足硬约束 → 422,附带问题清单(便于用户/演示解释)。"""
    return JSONResponse(
        status_code=422,
        content={"detail": {"message": exc.message, "issues": exc.issues, "attempts": exc.attempts}},
    )


def _default_hotel(city: str) -> tuple[float, float]:
    pois = load_city(city)
    lat = sum(p.lat for p in pois) / len(pois)
    lng = sum(p.lng for p in pois) / len(pois)
    return lat, lng


class CityList(BaseModel):
    cities: list[str]


@app.get("/api/health")
def health() -> dict:
    try:
        name = get_provider().name
        ready = name != "mock"  # mock 不再具备排程能力
    except ProviderError as e:
        return {"ok": True, "provider": "unavailable", "reason": e.message, "ready": False}
    return {"ok": True, "provider": name, "ready": ready}


@app.get("/api/cities", response_model=CityList)
def cities() -> CityList:
    return CityList(cities=available_cities())


@app.get("/api/cities/{city}/pois")
def city_pois(city: str):
    try:
        return load_city(city)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/preference-vocab")
def preference_vocab():
    """扩展软偏好词表(单一来源):前端榜单池 + 全局推荐选项。"""
    return load_preference_vocab()


# ---------------------------------------------------------------- 分步 AI 解析
class ParseRequest(BaseModel):
    text: str
    city: Optional[str] = None


@app.post("/api/parse/poi")
def parse_poi(body: ParseRequest):
    """第一步:把自然语言解析成**景点意愿**(四层 POI 偏好)。

    与 /api/parse/soft 分开,是为了让前端能把「AI 理解过程」分两步可视化。
    """
    provider = get_provider()
    pois = load_city(body.city) if body.city else []
    return provider.hydrate(body.text, pois)


@app.post("/api/parse/soft")
def parse_soft(body: ParseRequest):
    """第二步:把自然语言解析成**扩展软偏好**(体力/天气/作息/消费… 词表标签)。"""
    from .data.loader import vocab_tags

    try:
        return get_provider().parse_soft_prefs(body.text, vocab_tags())
    except Exception:
        return TagPref()  # 次要信息:失败不阻断主流程


@app.post("/api/trip", response_model=TripState)
def create_trip(body: TripCreate):
    if body.city not in available_cities():
        raise HTTPException(400, f"未知城市 {body.city},可选 {available_cities()}")
    if body.hotel_lat is None or body.hotel_lng is None:
        body.hotel_lat, body.hotel_lng = _default_hotel(body.city)
    trip = TripState(
        id="",
        city=body.city,
        days=body.days,
        total_budget=body.total_budget,
        initial_people=body.initial_people,
        hotel_lat=body.hotel_lat,
        hotel_lng=body.hotel_lng,
        start_at=body.start_at,
    )
    return store.create(trip)


def _current_day_for(trip: TripState, now: datetime | None = None) -> int:
    """按墙钟算出 trip 当前已进行到第几天(前 current_day 天冻结)。

    未开始(start_at 在未来或缺省)一律返回 0 —— 没有任何天被冻结。
    已开始:按 24 小时一天整除,clamp 到 [0, days-1](最后一天始终是"今天")。
    判定以这里为准;前端只做展示用的同款计算。
    """
    if not trip.start_at:
        return 0
    now = now or datetime.now()
    try:
        start = datetime.fromisoformat(trip.start_at)
    except ValueError:
        return 0
    if now < start:
        return 0
    elapsed_days = int((now - start).total_seconds() // 86400)
    return max(0, min(elapsed_days, trip.days - 1))


@app.post("/api/trip/{trip_id}/participants", response_model=TripState)
def add_participant(trip_id: str, body: ParticipantCreate):
    trip = _get_trip(trip_id)
    provider = get_provider()
    pois = load_city(trip.city)

    parsed: StructuredPref = StructuredPref()
    if body.natural_text.strip() and not body.already_parsed:
        try:
            parsed = provider.hydrate(body.natural_text, pois)
        except ProviderError as e:
            raise HTTPException(502, {"message": e.message})

    # 结构化覆盖优先;否则用 NL 解析结果。统一去重:同一地点只保留最高层级
    if body.structured is not None:
        final = StructuredPref()
        for level in ("refuse", "must", "want", "ok"):
            setattr(final, level, [x for x in getattr(body.structured, level) if x in {p.id for p in pois}])
        final = sanitize_pref(final)
    else:
        final = parsed

    # 扩展软偏好(词表 tag id;独立 id 空间,走 sanitize_tag_pref)
    soft_final = _resolve_soft(provider, body, trip, pois)

    existing = next((p for p in trip.participants if p.name == body.name), None)
    if existing:
        if body.merge and (body.natural_text.strip() or body.structured is not None or body.soft is not None):
            # 「再补充几句」:增量合并到已有倾向,不抹掉历史排位
            existing.pref = merge_prefs(existing.pref, final)
            if soft_final is not None:
                existing.soft = merge_tag_pref(existing.soft, soft_final)
            if body.natural_text.strip():
                existing.natural_inputs = [*existing.natural_inputs, body.natural_text.strip()]
                _sync_natural_text(existing)
        else:
            # 重新提交 = 覆盖(重新解析 / 点选编辑)
            existing.pref = final
            if soft_final is not None:
                existing.soft = soft_final
            if body.natural_text.strip():
                # 重新解析 → 输入历史重置为这一次(旧的表述已被取代)
                existing.natural_inputs = [body.natural_text.strip()]
                _sync_natural_text(existing)
    else:
        inputs = [body.natural_text.strip()] if body.natural_text.strip() else []
        trip.participants.append(Participant(
            id=uuid.uuid4().hex[:6],
            name=body.name,
            natural_text="；".join(inputs),
            natural_inputs=inputs,
            pref=final,
            soft=soft_final or TagPref(),
        ))
    sync_essentials(trip)  # auto 模式:新成员/改偏好后重估食宿单价
    store.save(trip)
    return trip


def _sync_natural_text(p: Participant) -> None:
    """natural_text 是从输入历史派生的兼容字段,保持两者一致。"""
    p.natural_text = "；".join(p.natural_inputs)


def _resolve_soft(provider, body: ParticipantCreate, trip: TripState, pois) -> Optional[TagPref]:
    """解析扩展软偏好:structured 优先,其次 NL,都没有则 None(表示不改动)。"""
    if body.soft is not None:
        valid = vocab_tag_ids()
        out = TagPref()
        for level in ("refuse", "must", "want", "ok"):
            setattr(out, level, [x for x in getattr(body.soft, level) if x in valid])
        return sanitize_tag_pref(out)
    if body.natural_text.strip() and not body.already_parsed:
        from .data.loader import vocab_tags

        try:
            soft = provider.parse_soft_prefs(body.natural_text, vocab_tags())
        except Exception:
            return None  # 软偏好是次要信息,解析失败不阻塞成员创建
        if any(getattr(soft, lv) for lv in ("refuse", "must", "want", "ok")):
            return sanitize_tag_pref(soft)
    return None


class BudgetPatch(BaseModel):
    """食宿经济口径(规则页可选):auto=按偏好估计 / manual=手动单价。"""
    mode: Optional[str] = None
    food_per_head: Optional[float] = None
    lodging_per_head: Optional[float] = None


class SettingsPatch(BaseModel):
    natural_text: str = ""
    settings: Optional[RecoSettings] = None
    budget: Optional[BudgetPatch] = None


@app.patch("/api/trip/{trip_id}/settings", response_model=TripState)
def update_settings(trip_id: str, body: SettingsPatch):
    """写全局推荐设置。natural_text 交给 AI 预处理,或直接传结构化 settings;食宿预算可选。"""
    trip = _get_trip(trip_id)
    if body.settings is not None:
        trip.settings = body.settings
    elif body.natural_text.strip():
        provider = get_provider()
        try:
            parsed = provider.parse_reco_settings(body.natural_text)
        except ProviderError as e:
            raise HTTPException(502, {"message": e.message})
        parsed.raw_text = body.natural_text
        trip.settings = parsed
    if body.budget is not None:
        b = body.budget
        if b.mode in ("auto", "manual"):
            trip.budget_mode = b.mode
        if b.food_per_head is not None:
            trip.food_per_head = max(0.0, b.food_per_head)
        if b.lodging_per_head is not None:
            trip.lodging_per_head = max(0.0, b.lodging_per_head)
        if trip.budget_mode == "auto":
            sync_essentials(trip)  # manual 下保留用户值;auto 下按偏好重估
    store.save(trip)
    return trip


@app.get("/api/trip/{trip_id}", response_model=TripState)
def get_trip(trip_id: str):
    trip = _get_trip(trip_id)
    store.sweep_checkins()  # 打开行程的同时推进图鉴(已开始行程的冻结天自动打卡)
    return trip


@app.post("/api/trip/{trip_id}/plan", response_model=PlanResult)
def make_plan(trip_id: str):
    """生成行程。白盒已移除,决策完全由 AI 完成;失败不写 current_plan。"""
    trip = _get_trip(trip_id)
    if not trip.participants:
        raise HTTPException(400, "先添加至少一位成员及偏好")
    try:
        plan = ai_plan(trip)
    except PlanValidationError as e:
        raise HTTPException(422, {"message": e.message, "issues": e.issues, "attempts": e.attempts})
    except ProviderError as e:
        raise HTTPException(502, {"message": e.message})
    trip.current_plan = plan
    store.save(trip)
    return plan


@app.post("/api/trip/{trip_id}/replan", response_model=ReplanResult)
def make_replan(trip_id: str, body: ReplanRequest):
    """更新行程:冻结已过期的天,重排剩余天。

    - `current_day` 缺省 → 自动按 `trip.start_at` 与墙钟计算(行程已开始后线程内随时可点)。
    - `participant_id` 缺省 → 纯重排:不改任何成员(偏好/规则页的改动已各自持久化,这里直接重算剩余天)。
    """
    trip = _get_trip(trip_id)
    if not trip.current_plan:
        raise HTTPException(400, "请先生成一次行程再更新")
    current_day = body.current_day if body.current_day is not None else _current_day_for(trip)

    # ---- 有明确成员要改:走原有的「改偏好 → 重排」路径(含 NL 解析)----
    if body.participant_id:
        target = next((p for p in trip.participants if p.id == body.participant_id), None)
        if target is None:
            raise HTTPException(404, "成员不存在")
        provider = get_provider()
        pois = load_city(trip.city)
        try:
            parsed = provider.hydrate(body.natural_text, pois) if body.natural_text.strip() else StructuredPref()
        except ProviderError as e:
            raise HTTPException(502, {"message": e.message})
        new_pref = StructuredPref()
        for level in ("refuse", "must", "want", "ok"):
            override = getattr(body.structured, level, []) if body.structured else []
            setattr(new_pref, level, override if override else getattr(parsed, level))
        new_pref = sanitize_pref(new_pref)

        new_soft = None
        if body.soft is not None:
            new_soft = sanitize_tag_pref(body.soft)
        elif body.natural_text.strip():
            from .data.loader import vocab_tags
            s = provider.parse_soft_prefs(body.natural_text, vocab_tags())
            if any(getattr(s, lv) for lv in ("refuse", "must", "want", "ok")):
                new_soft = s
    else:
        # ---- 纯重排:没有任何成员偏好要改 ----
        target = None
        new_pref = StructuredPref()
        new_soft = None

    try:
        result = replan(trip, body.participant_id, new_pref, current_day, new_soft=new_soft)
    except PlanValidationError as e:
        raise HTTPException(422, {"message": e.message, "issues": e.issues, "attempts": e.attempts})
    except ProviderError as e:
        raise HTTPException(502, {"message": e.message})
    # 把这次动态调整的自然语言记入该成员的输入历史
    if body.natural_text.strip() and target is not None:
        target.natural_inputs = [*target.natural_inputs, body.natural_text.strip()]
        _sync_natural_text(target)
    store.save(trip)
    return result


def _get_trip(trip_id: str) -> TripState:
    try:
        return store.require(trip_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/trip/{trip_id}/weather")
def get_trip_weather(trip_id: str):
    """行程逐日真实天气(供行程页展示)。取不到时 days 为空列表 —— 前端不显示即可。"""
    from .data.weather import fetch_weather_for_trip
    return {"days": fetch_weather_for_trip(_get_trip(trip_id))}


# ================================================================ 五栏外壳(管理/图鉴/社区/个人)
@app.get("/api/trips", response_model=list[TripState])
def list_trips():
    """管理页:全部行程,按创建时间倒序。"""
    return store.all_trips()


@app.delete("/api/trip/{trip_id}", status_code=204)
def delete_trip(trip_id: str):
    try:
        store.remove(trip_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/profile", response_model=Profile)
def get_profile():
    return store.profile


class ProfilePatch(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None


@app.patch("/api/profile", response_model=Profile)
def patch_profile(body: ProfilePatch):
    return store.set_profile(**body.model_dump(exclude_unset=True))


@app.get("/api/collection")
def get_collection():
    """图鉴:先推进自动打卡(已开始行程的冻结天),再返回全部记录 + 每城进度。

    注意 visited 只数 **count > 0** 的记录 —— 手动取消打卡后 count=0,进度必须回退。
    """
    store.sweep_checkins()
    records = list(store.collection().values())
    from .data.loader import available_cities, load_city
    progress = {
        city: {
            "visited": sum(1 for r in records if r.city == city and r.count > 0),
            "total": len(load_city(city)),
        }
        for city in available_cities()
    }
    return {"records": records, "progress": progress}


class CollectionToggle(BaseModel):
    visited: bool


@app.post("/api/collection/{poi_id}", response_model=CheckInRecord)
def toggle_collection(poi_id: str, body: CollectionToggle):
    """手动勾/取消打卡。POI 必须存在。"""
    from .data.loader import available_cities, load_city
    city = next((c for c in available_cities()
                 if any(p.id == poi_id for p in load_city(c))), None)
    if city is None:
        raise HTTPException(404, f"未知景点 {poi_id}")
    if body.visited:
        return store.checkin(poi_id, city)
    store.uncheckin(poi_id)
    return store.collection().get(poi_id) or CheckInRecord(poi_id=poi_id, city=city, count=0)


# ------------------------------------------------ 社区
MAX_PHOTOS_PER_SECTION = 4
MAX_PHOTOS_PER_POST = 9
MAX_SECTIONS = 12


class PostCreate(BaseModel):
    """发帖请求 —— 内容只来自行程分享,故 trip_id 必填。

    刻意**不校验**行程是否存在、poi_id/day 是否属于该行程:帖子是内容沉淀,
    来源行程被删或重排后仍要能渲染(title/subtitle 已是冗余展示串)。
    """

    city: str
    trip_id: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=2000)
    poi_ids: list[str] = []
    sections: list[PostSection] = Field(default_factory=list, max_length=MAX_SECTIONS)

    @field_validator("sections")
    @classmethod
    def _check_sections(cls, v: list[PostSection]) -> list[PostSection]:
        total = 0
        for s in v:
            if s.kind == "poi" and not s.poi_id:
                raise ValueError("地点段落缺少地点")
            if s.kind == "day" and s.day is None:
                raise ValueError("日期段落缺少天数")
            if len(s.photos) > MAX_PHOTOS_PER_SECTION:
                raise ValueError(f"每个段落最多 {MAX_PHOTOS_PER_SECTION} 张照片")
            for ph in s.photos:
                if not ph.data.startswith("data:image/") or ";base64," not in ph.data:
                    raise ValueError("照片必须是 data:image/* 的 base64 图片")
            total += len(s.photos)
        if total > MAX_PHOTOS_PER_POST:
            raise ValueError(f"一篇帖子最多 {MAX_PHOTOS_PER_POST} 张照片")
        return v

    @model_validator(mode="after")
    def _check_not_empty(self) -> "PostCreate":
        if not self.text.strip() and not self.sections:
            raise ValueError("帖子至少要有正文或一个图文段落")
        return self


class CommentCreate(BaseModel):
    text: str
    author: str = ""


@app.get("/api/posts")
def get_posts():
    """社区信息流:帖子(含各自评论)按创建倒序。"""
    return [
        {**p.model_dump(), "comments": [c.model_dump() for c in store.comments(p.id)]}
        for p in store.posts()
    ]


@app.post("/api/posts", response_model=Post)
def create_post(body: PostCreate):
    prof = store.profile
    return store.add_post(prof.name, prof.avatar, body.city, body.text, body.poi_ids,
                          trip_id=body.trip_id, sections=body.sections)


@app.post("/api/posts/{post_id}/like", response_model=Post)
def like_post(post_id: str):
    """点赞/取消点赞(toggle)。单用户只能点一次:再点即撤回。"""
    post = store.toggle_like(post_id)
    if post is None:
        raise HTTPException(404, "帖子不存在")
    return post


@app.post("/api/posts/{post_id}/comments", response_model=Comment)
def add_comment(post_id: str, body: CommentCreate):
    comment = store.add_comment(post_id, body.author or store.profile.name, body.text)
    if comment is None:
        raise HTTPException(404, "帖子不存在")
    return comment
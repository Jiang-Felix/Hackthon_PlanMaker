"""Pydantic 数据模型 —— API 输入输出与内部状态结构。"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- POI 数据
class POI(BaseModel):
    """内置精选景点/场所。open 形如 "09:00-17:00",hours 为建议游览小时数。"""

    id: str
    name: str = Field(description="中文名")
    emoji: str = "📍"
    lat: float
    lng: float
    price: float = Field(default=0, description="门票/人均消费,元")
    hours: float = Field(default=2, description="建议游览时长(小时)")
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list, description="别名/昵称,用于模糊匹配,如 迪士尼/水族馆/观星")
    open: str = Field(default="09:00-21:00", description="开放时间,如 09:00-21:00")
    desc: str = ""


# ---------------------------------------------------------------- 偏好
# 层级:可拒绝/必去/想去/可接受 —— refuse 为硬排除
PrefLevel = Literal["refuse", "must", "want", "ok"]


class StructuredPref(BaseModel):
    """结构化偏好:每个层级是 POI id 列表。"""

    refuse: list[str] = Field(default_factory=list)
    must: list[str] = Field(default_factory=list)
    want: list[str] = Field(default_factory=list)
    ok: list[str] = Field(default_factory=list)


class TagPref(BaseModel):
    """扩展软偏好:与 StructuredPref 同形,但承载的是**词表 tag id**(非 POI id)。

    刻意与 StructuredPref 并列而不合并 —— sanitize_pref 假设四层互斥且被多处调用,
    混入 tag id 会污染语义。两者各自有独立的 sanitize/merge。
    """

    refuse: list[str] = Field(default_factory=list)
    must: list[str] = Field(default_factory=list)
    want: list[str] = Field(default_factory=list)
    ok: list[str] = Field(default_factory=list)


class VocabTag(BaseModel):
    """词表扁平化后的标签项(前端榜单池 / AI 解析共用)。"""

    id: str
    label: str
    emoji: str = "🏷️"
    category: str = Field(description="所属类别 key")
    category_label: str = ""
    aliases: list[str] = Field(default_factory=list)


class RecoSettings(BaseModel):
    """全局推荐设置(评审「Recommendation Logic Design」)。"""

    conflict_strategy: Literal["rotate", "split", "majority"] = Field(
        default="rotate", description="冲突解决:轮换优先/分组出游/服从多数")
    schedule_align: Literal["left", "center", "right", "fill"] = Field(
        default="fill", description="日程对齐:左/居中/右/填充")
    activity_priorities: list[str] = Field(
        default_factory=list, description="活动关联优先级(有序):avoid_similar/cluster_theme/food_balance")
    buffer_min: int = Field(default=15, ge=0, le=180, description="景点间留白时间(分钟)")
    max_wait_min: int = Field(default=30, ge=0, le=180, description="最坏等待时间上限(分钟)")
    raw_text: str = Field(default="", description="用户原始自然语言输入")


class ParticipantCreate(BaseModel):
    """成员创建:natural_text 交给 AI 解析,NL 解析结果可被 structured 覆盖。

    merge=True 时表示「补充几句」:在已有偏好上增量合并,不抹掉历史排位。
    """

    name: str
    natural_text: str = ""
    structured: Optional[StructuredPref] = None
    soft: Optional[TagPref] = Field(default=None, description="扩展软偏好(词表 tag id)")
    merge: bool = False
    already_parsed: bool = Field(
        default=False,
        description="natural_text 仅记入输入历史,不再调用 AI 解析(前端已用 /api/parse/* 自行解析)")


class Participant(BaseModel):
    id: str
    name: str
    natural_text: str = Field(default="", description="全部自然语言输入的合并串(兼容字段)")
    natural_inputs: list[str] = Field(
        default_factory=list, description="自然语言输入历史:[0]=原始输入,后续为每次「再补充几句」")
    pref: StructuredPref = Field(default_factory=StructuredPref)
    soft: TagPref = Field(default_factory=TagPref)


# ---------------------------------------------------------------- 行程
class TripCreate(BaseModel):
    city: str = Field(description="城市标识:shanghai / hangzhou / chengdu")
    days: int = Field(default=2, ge=1, le=7)
    total_budget: float = Field(default=1500, ge=1)
    initial_people: int = Field(
        default=3, ge=1, le=8,
        description="初始人数:创建时设定的同行人数,「偏好」页据此预置待填写成员位(不直接建成员)")
    hotel_lat: Optional[float] = None
    hotel_lng: Optional[float] = None
    start_at: Optional[str] = Field(
        default=None,
        description="出发日期时间,本地 ISO 'YYYY-MM-DDTHH:MM'(无时区)。缺省 = 旧行为,永不自动冻结。")


class ReplanRequest(BaseModel):
    participant_id: Optional[str] = Field(
        default=None, description="谁改主意了;None = 纯重排(冻结已过期天,重排剩余天),不改任何成员")
    natural_text: str = ""
    structured: Optional[StructuredPref] = None
    soft: Optional[TagPref] = None
    current_day: Optional[int] = Field(
        default=None, ge=0, description="自第几天起重排(已执行天数冻结);None = 按 trip.start_at 与当前时间自动计算")


# ---------------------------------------------------------------- 排程产物
class DayStop(BaseModel):
    poi_id: str
    name: str
    emoji: str = "📍"
    arrive_min: int = Field(description="到达(分钟,自当日0点)")
    start_min: int = Field(description="开始游览")
    end_min: int = Field(description="结束游览")
    travel_min: int = Field(default=0, description="为到达本点花费的移动时间")
    travel_mode: str = Field(default="步行", description="步行/打车")
    travel_cost: float = Field(default=0)
    price: float = Field(default=0)
    tags: list[str] = Field(default_factory=list)


class DayPlan(BaseModel):
    day: int = Field(description="第几天,0 起")
    stops: list[DayStop] = Field(default_factory=list)
    day_spent: float = Field(default=0, description="当天全队花销 = 门票×人数 + 打车 + 当天食宿")
    day_end_note: str = ""


class CostBreakdown(BaseModel):
    """全队花销分项(评审经济计算的核心展示)。"""

    tickets: float = Field(default=0, description="门票合计 = Σ(人均门票 × N 人)")
    transport: float = Field(default=0, description="打车合计(全队共享,按趟计)")
    food: float = Field(default=0, description="餐饮合计 = 每人每天餐费 × N × 天")
    lodging: float = Field(default=0, description="住宿合计 = 每人每晚 × N × 天")
    per_head_food: float = Field(default=0, description="每人每天餐费")
    per_head_lodging: float = Field(default=0, description="每人每晚住宿")


class Explanation(BaseModel):
    poi_id: str
    included: bool
    title: str = Field(description="一句结论,如「为什么保留 X」")
    reasons: list[str] = Field(default_factory=list, description="理由要点")
    who_likes: list[str] = Field(default_factory=list, description="哪些成员的本层偏好被命中")
    who_conceded: list[str] = Field(default_factory=list, description="因取舍让了步的成员")
    level: str = ""


ConcessionKind = Literal["passed_over", "out_of_capacity", "refused_by_other"]


class Concession(BaseModel):
    """让步账本条目:谁让出了哪个地点、**为什么**让。

    kind 记录真实原因(旧版的 `winner_poi` 永远是空串,已删):
    - passed_over       本可安排却未被采纳 —— 唯一进入 FairnessReport.concessions 的一类
    - out_of_capacity   时间/预算确实塞不下
    - refused_by_other  被他人明确列为『不去』
    后两类只作为 notes 流向 explanations,不计入让步账本(见 concessions.py 模块 docstring)。
    """

    round: int
    participant_id: str
    participant_name: str
    loser_poi: str
    kind: ConcessionKind = "passed_over"
    reason: str


class FairnessReport(BaseModel):
    participants: list["FairnessRow"] = Field(default_factory=list)
    concessions: list[Concession] = Field(default_factory=list)
    summary_messages: list[str] = Field(default_factory=list)
    contested_slots: int = Field(default=0, description="S:有人想要的已排停留数")
    undeclared_slots: int = Field(default=0, description="U:无人声明的已排停留数(填充项)")
    quota: float = Field(default=0, description="S/n:人均可分到的名额")


class FairnessRow(BaseModel):
    """一个人的公平账 —— 回答「TA 这次被牺牲了吗、被牺牲了多少」。

    口径(详见 scheduler/fairness.py 公式注释):
    - `share` 不是划分,可能 >1、不必求和为 100%(一个停留可同时满足两人)。
      **禁止**用 mean(share) 当"综合公平度"。
    - 粒度上 2 天行程 quota≈1-3,一个名额就摆动 33-50%,**比率在阈值上是噪声** ——
      颜色请用整数 `deficit`,比率只作文本展示。
    """

    participant_id: str
    name: str
    # 硬地板(守门层保证 100%)
    must_met: int = 0
    must_total: int = 0
    # 容量配比 —— 新主指标
    slots_got: int = Field(default=0, description="排入的、属于 TA 的意愿数量")
    wants_declared: int = Field(default=0, description="声明的意愿数(∩ 本城合法 POI)")
    slots_owed: Optional[float] = Field(default=None, description="应得名额 = min(声明数, 人均配额)")
    share: Optional[float] = Field(default=None, description="拿到/应得,封顶 1;None = 未提意愿")
    deficit: int = Field(default=0, description="整数缺口 max(0, round(应得-拿到)) —— 着色依据")
    # 软偏好(AI 自评)。未评估 ≠ 未满足:soft_cared==0 时 soft_rate 必须是 None,不能是 0
    soft_declared: int = 0
    soft_cared: int = Field(default=0, description="被评估到的软偏好数(分母);0 表示未评估")
    soft_rate: Optional[float] = None
    soft_satisfied: list[str] = Field(default_factory=list, description="被照顾到的 tag id")
    soft_missed: list[str] = Field(default_factory=list, description="被评估为未照顾到的 tag id")
    soft_violated: list[str] = Field(default_factory=list, description="被违反的软 refuse tag id")
    soft_unaccounted: list[str] = Field(
        default_factory=list,
        description="模型没给出裁决的已声明 tag id —— 非空即自评不完整,必须如实报出",
    )
    # 明细与账本
    satisfied: dict[str, list[str]] = Field(default_factory=dict, description="各层级已满足的 POI id")
    missing: dict[str, list[str]] = Field(default_factory=dict, description="各层级未满足的 POI id")
    concession_count: int = 0


class PlanResult(BaseModel):
    trip_name: str = ""
    city: str
    days: list[DayPlan] = Field(default_factory=list)
    explanations: list[Explanation] = Field(default_factory=list)
    fairness: FairnessReport = Field(default_factory=FairnessReport)
    total_spent: float = Field(default=0, description="全队合计 = 门票×人数 + 打车 + 食宿")
    total_budget: float = Field(default=0)
    engine: str = Field(default="ai", description="决策来源:ai=AI 编排(白盒已移除)")
    cost_breakdown: CostBreakdown = Field(default_factory=CostBreakdown)


class ReplanResult(BaseModel):
    plan: PlanResult
    added: list[str] = Field(default_factory=list, description="本次新换入的 POI id")
    removed: list[str] = Field(default_factory=list, description="本次被换出的 POI id")
    affected: list[str] = Field(default_factory=list, description="满意度变化的成员 id")


class TripState(BaseModel):
    id: str
    city: str
    days: int
    total_budget: float
    initial_people: int = Field(default=3, ge=1, le=8, description="创建时设定的初始人数(偏好页预置成员位用)")
    hotel_lat: float
    hotel_lng: float
    start_at: Optional[str] = Field(
        default=None,
        description="出发日期时间(本地 ISO)。已开始 = 当前时间 >= start_at;前 current_day 天按墙钟自动冻结。")
    created_at: str = Field(default="", description="创建时间(ISO),「管理」列表排序/显示用")
    # 食宿经济口径(评审经济计算):
    # budget_mode=auto → 按成员偏好自动估计单价;manual → 用用户在规则页填的值。
    budget_mode: str = Field(default="auto", description="auto=按偏好估计食宿 / manual=手动配置")
    food_per_head: float = Field(default=90.0, description="每人每天餐费(元)")
    lodging_per_head: float = Field(default=180.0, description="每人每晚住宿(元)")
    participants: list[Participant] = Field(default_factory=list)
    settings: RecoSettings = Field(default_factory=RecoSettings)
    current_plan: Optional[PlanResult] = None


# ---------------------------------------------------------------- 五栏外壳(社区/图鉴/个人)
class Profile(BaseModel):
    """「个人」页的单用户资料(此赛道无多用户登录)。"""

    name: str = "旅行者"
    avatar: str = "🧭"
    bio: str = ""


class CheckInRecord(BaseModel):
    """图鉴打卡记录:visited = count > 0。auto 天自动 +1,手动可增/减。"""

    poi_id: str
    city: str
    count: int = 0
    first_at: str = Field(default="", description="首次打卡时间(ISO)")


# ---------------------------------------------------------------- 社区
# 帖子的图文段落按「地点」或「按天」组织(行程分享的扩展能力)
PhotoKind = Literal["poi", "day"]


class PostPhoto(BaseModel):
    """帖子照片:客户端压缩后的 data URL。内存态演示,不做文件存储。"""

    id: str = Field(default="", description="由 store 生成,输入时留空")
    data: str = Field(description='形如 "data:image/jpeg;base64,..."')
    caption: str = ""


class PostSection(BaseModel):
    """帖子的一段:按「地点」或「按天」聚合的照片 + 文字评论。

    `title`/`subtitle` 是**冗余展示串**(如 "外滩"/"10:00–12:00"、"第 2 天"/"9/28 周日"),
    刻意不靠 trip_id 反查 —— 帖子是内容沉淀,来源行程被删后仍要能渲染。
    """

    kind: PhotoKind
    poi_id: str = Field(default="", description='kind=="poi":行程里的 POI id')
    day: Optional[int] = Field(default=None, description='kind=="day":0 起的天下标')
    title: str = ""
    subtitle: str = ""
    note: str = ""
    photos: list[PostPhoto] = Field(default_factory=list)


class Post(BaseModel):
    """社区帖子 —— 内容**只来自行程分享**,故 trip_id 必填(端点校验)。

    author 用 profile 昵称;除通常的正文/景点卡外,可带按地点或按天组织的图文段落。
    """

    id: str
    author: str
    avatar: str = "🧑🎤"
    city: str
    text: str
    created_at: str = ""
    poi_ids: list[str] = Field(default_factory=list)
    trip_id: str = Field(default="", description="来源行程 id(仅存档,前端不据此反查)")
    sections: list[PostSection] = Field(default_factory=list, description="按地点/按天的图文段落")
    likes: int = 0
    liked: bool = False


class Comment(BaseModel):
    id: str
    post_id: str
    author: str
    text: str
    created_at: str = ""
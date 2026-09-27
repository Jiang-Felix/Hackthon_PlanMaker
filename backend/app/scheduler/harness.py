"""AI-harness 编排层 —— 行程生成的唯一入口(白盒决策引擎已按要求移除)。

职责边界(重要):
- **AI 决策**:provider.draft_itinerary 依据「统一标准格式化的上下文」生成逐日草案。
- **守门校验**:草案不得违反 时间窗/预算/refuse/开放时间,且每位成员的『必去』
  必须被覆盖(评审第 2 条防平均主义)。校验器只守**硬地板**,不评判软偏好语义。
- **修复**:失败清单回喂 AI 修正(≤2 轮)。
- **无兜底**:仍不达标 → 抛 PlanValidationError。不做静默降级(白盒已移除)。

评审三条原则在去白盒后靠「prompt 硬要求(决策宪法)+ must 覆盖率校验」双轨保证。
"""

from __future__ import annotations

import json

from ..ai.provider import get_provider
from ..data.loader import pois_by_id, vocab_tags
from ..data.weather import fetch_weather_for_trip
from ..errors import PlanValidationError
from ..models import Concession, DayStop, FairnessRow, POI, RecoSettings, TripState
from .concessions import audit_concessions
from .constraints import can_add
from .assembly import build_plan

MAX_REVISE = 2


# ------------------------------------------------------------------ 上下文
def _pref_to_names(pref, pois: dict[str, POI]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for lv in ("refuse", "must", "want", "ok"):
        ids = getattr(pref, lv)
        if ids:
            out[lv] = [pois[x].name if x in pois else x for x in ids]
    return out


def _soft_to_labels(soft, label_of: dict[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for lv in ("refuse", "must", "want", "ok"):
        ids = getattr(soft, lv)
        if ids:
            out[lv] = [label_of.get(x, x) for x in ids]
    return out


def _settings_line(s: RecoSettings) -> str:
    from ..data.loader import reco_options
    opts = reco_options()

    def label(group: str, value: str) -> str:
        for item in opts.get(group, []):
            if item["id"] == value:
                return item["label"]
        return value

    prio = " > ".join(
        next((i["label"] for i in opts.get("activity_priorities", []) if i["id"] == p), p)
        for p in s.activity_priorities
    ) or "无特别偏好"
    return (
        f"冲突解决={label('conflict_strategy', s.conflict_strategy)}; "
        f"日程对齐={label('schedule_align', s.schedule_align)}; "
        f"活动关联优先={prio}; "
        f"景点间留白={s.buffer_min}分钟; 排队等待上限={s.max_wait_min}分钟"
    )


def build_context(
    trip: TripState,
    pois: dict[str, POI],
    *,
    start_day: int = 0,
    freeze: dict[int, list[DayStop]] | None = None,
    prior_rows: list[FairnessRow] | None = None,
    weather: list[dict] | None = None,
) -> str:
    """统一标准化的上下文 —— AI 决策端的全部输入(首排与重排共用)。

    `weather` 是 `data.weather.fetch_weather_for_trip` 的逐日真实预报(取不到传 None/[]);
    本函数是**纯函数**,不自己发请求 —— 便于单测注入固定天气。
    """
    from .cost import essentials_total

    label_of = {t.id: t.label for t in vocab_tags()}
    n = max(1, len(trip.participants))
    ess = essentials_total(trip)
    disposable = trip.total_budget - ess
    lines = [
        "行程规划请求(统一格式):",
        f"【行程基线】城市={trip.city};天数={trip.days};人数={n};总预算=¥{trip.total_budget:.0f};"
        f"食宿固定{'(每人每天餐¥%s+每晚宿¥%s)×%d人×%d天=¥%d' % (trip.food_per_head, trip.lodging_per_head, n, trip.days, ess)};"
        f"门票+交通可用预算=¥{disposable:.0f}(门票按每人×{n}人,打车全队共享一趟);每日窗口=09:00-21:00",
        "【每日容量提示】一天只有 12 小时。游览时长 ≥5 小时的项目(如乐园、远郊景点)"
        "请让它**独占当天**,不要再往同一天塞别的项目;安排不下时宁可少排、不要硬塞。",
    ]
    if weather:
        lines.append(
            "【每日天气(真实预报)】结合天气与成员偏好做取舍:雨天/高温优先**室内**项目、"
            "把户外/观景排在晴好的天;成员若声明『下雨不出门』或『偏好室内』务必照办。"
        )
        for i, w in enumerate(weather):
            tmax, tmin, precip = w.get("tmax"), w.get("tmin"), w.get("precip")
            temp = f"{tmin:.0f}~{tmax:.0f}℃" if tmin is not None and tmax is not None else ""
            rain = f" 降水 {precip:.0f}%" if precip is not None else ""
            lines.append(
                f"  Day{i + 1}({w.get('date', '')}):{w.get('icon', '')}{w.get('text', '')} {temp}{rain}".rstrip()
            )
    lines.append("【成员偏好】(级别:refuse=不去 must=必去 want=想去 ok=可接受)")
    for p in trip.participants:
        lines.append(f"  - {p.name} 核心意愿:{json.dumps(_pref_to_names(p.pref, pois), ensure_ascii=False)}")
        soft = _soft_to_labels(p.soft, label_of)
        if soft:
            lines.append(f"      扩展偏好:{json.dumps(soft, ensure_ascii=False)}(标签语义见下)")

    lines.append(f"【全局推荐设置】{_settings_line(trip.settings)}")

    if freeze:
        lines.append("【已执行,严禁改动或重复】")
        for day in sorted(freeze):
            for st in freeze[day]:
                lines.append(f"  Day{day} {st.start_min // 60:02d}:{st.start_min % 60:02d}"
                             f"-{st.end_min // 60:02d}:{st.end_min % 60:02d} {st.name}({st.poi_id})")
        lines.append(f"  剩余须安排的天:{list(range(start_day, trip.days))}")

    if prior_rows:
        # 轮换优先权 = **当前欠账**(应得名额 - 实际拿到),不是累计让步次数。
        # 旧版用累计次数,只增不减 —— 谁先让一次就永久受照顾。用 deficit 则自带
        # 闭环:补偿到位后 deficit 归零,优先权自动消失。
        owed = [(r.name, r.deficit) for r in prior_rows if r.deficit > 0]
        if owed:
            desc = ";".join(f"{n}上轮少安排 {d} 个" for n, d in owed)
            lines.append(f"【轮换优先权】{desc} —— 本轮请优先照顾 TA 的诉求(轮换)")

    lines.append("【可用景点】id 名称 开放 价格(每人) 时长 [标签]")
    for poi in pois.values():
        lines.append(f"  - {poi.id} {poi.name} {poi.open} ¥{poi.price:.0f} {poi.hours}h [{','.join(poi.tags)}]")

    lines.extend([
        "【决策宪法 —— 必须遵守】",
        "1. 【平衡≠平均】分层权重 必去10 > 想去4 > 可接受1;不以数量取胜,不生成「谁都能接受但谁都不满意」的折中。",
        "1.1 【id 必须逐字复制】stops 里只能填【可用景点】中**原样给出的 id**(形如 sh12 / cd01);"
        "严禁编造英文名、拼音、翻译名或自造 id。填错 id 视为方案不合格。",
        "2. 【防平均主义】每位成员的全部『必去』必须纳入(缺一即不合格);一个必去不得被他人若干普通偏好稀释。",
        "3. 【最低满意度+轮换】不得让任何成员一个高优先级诉求都落空;若上面给出了『轮换优先权』,欠账多者优先照顾。",
        "4. 【硬约束】只用上面列出的 id;refuse 严禁放入;遵守每个景点的开放时间与 09:00-21:00;"
        f"总花费(门票按每人×{n}人 + 打车一趟 + 食宿)不得超总预算 ¥{trip.total_budget:.0f};"
        f"景点部分不得超过门票+交通可用预算 ¥{disposable:.0f}。",
        "4.1 【冲突优先级】当『甲的必去』恰好是『乙的不去』时,**必去优先**(规则 2 高于规则 4);"
        "该地点应纳入行程,并在解释里说明这是经协商的让步。反之,非必去的被拒地点一律排除。",
        "5. 【软偏好与全局设置】是有效条件,请一并尊重(如体力/天气/作息/消费倾向、留白与等待上限)。",
        f"6. 【输出】严格 JSON,不要代码块:{{\"days\":[{{\"day\":0,\"stops\":[\"poi_id\", ...]}}, ...]}}"
        + (f";只输出 day ∈ {list(range(start_day, trip.days))}" if start_day else ""),
    ])
    return "\n".join(lines)


# ------------------------------------------------------------------ 守门校验
def _parse_draft(text: str) -> dict[int, list[str]]:
    """解析 AI 草案 JSON → {day: [poi_id]}。解析失败返回空(触发修复/报错)。"""
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    days: dict[int, list[str]] = {}
    for item in payload.get("days", []) if isinstance(payload, dict) else []:
        try:
            day = int(item.get("day", 0))
        except (TypeError, ValueError):
            day = 0
        stops = item.get("stops") or []
        days.setdefault(day, []).extend(str(s) for s in stops if isinstance(s, str))
    return days


def _validate(
    trip: TripState,
    pois: dict[str, POI],
    draft: dict[int, list[str]],
    *,
    start_day: int = 0,
    freeze: dict[int, list[DayStop]] | None = None,
) -> tuple[list[str], list[str], dict[int, list[DayStop]]]:
    """守门校验:逐项按序模拟。返回 (阻塞问题, 被裁掉的问题, 可行停留)。

    **阻塞 vs 可裁** —— 这是关键的严重程度区分:
    - 某人『必去』缺失 → **阻塞**,必须回喂 AI 重排(不能悄悄丢掉别人的必去)
    - 非必去项(想去/可接受)当天放不下 → **可裁**,直接裁掉并继续;
      这就是人类规划师会做的取舍,后续由让步账本如实记录。
    软偏好语义不进校验器(由 AI 在 prompt 约束下负责),避免校验器膨胀成新白盒。
    """
    hotel = (trip.hotel_lat, trip.hotel_lng)
    refused = {pid for p in trip.participants for pid in p.pref.refuse}
    must_ids = {pid for p in trip.participants for pid in p.pref.must}
    n = max(1, len(trip.participants))
    # 经济口径:食宿是固定承诺先扣掉,门票+交通在剩余可用预算里竞争;门票按每人×N。
    from .cost import essentials_total
    ess = essentials_total(trip)
    disposable = trip.total_budget - ess

    # 食宿就已经吃光/超了总预算 → 直接给一句**可操作**的说明,不要吐一串
    # "会超出剩余预算(车费 ¥0)" 这种让人摸不着头脑的级联报错。
    if trip.participants and disposable <= 0:
        return (
            [f"总预算 ¥{trip.total_budget:.0f} 还不够覆盖 {n} 人 {trip.days} 天的食宿"
             f"(按当前口径约 ¥{ess:.0f}),所以一个景点也排不下。"
             f"请调高总预算,或在「规则」页把食宿改成「手动」并填更低的单价。"],
            [],
            {d: list(s) for d, s in (freeze or {}).items()},
        )

    stops: dict[int, list[DayStop]] = {d: list(s) for d, s in (freeze or {}).items()}
    used: set[str] = {st.poi_id for s in stops.values() for st in s}
    spent = sum(st.price * n + st.travel_cost for s in stops.values() for st in s)
    blocking: list[str] = []
    trimmed: list[str] = []

    for day in range(start_day, trip.days):
        cur, prev = 0, None
        day_stops: list[DayStop] = []
        for pid in draft.get(day, []):
            if pid in used:
                continue
            poi = pois.get(pid)
            if poi is None:
                trimmed.append(f"第 {day + 1} 天:有个不认识的景点被忽略了")
                continue
            if pid in refused and pid not in must_ids:
                trimmed.append(f"第 {day + 1} 天:{poi.name} 有人说了『不去』,已从行程里拿掉")
                continue
            from_poi = pois.get(prev.poi_id) if prev else None
            stop, err = can_add(poi, from_poi, hotel, cur, disposable - spent, headcount=n)
            if stop is None:
                (blocking if pid in must_ids else trimmed).append(
                    f"第 {day + 1} 天:{poi.name} {err}")
                continue
            day_stops.append(stop)
            used.add(pid)
            spent += stop.price * n + stop.travel_cost
            cur = stop.end_min
            prev = stop
        if day_stops:
            stops.setdefault(day, [])
            stops[day] = stops.get(day, []) + day_stops

    # 必去覆盖是硬地板
    for p in trip.participants:
        for mid in p.pref.must:
            if mid not in used:
                blocking.append(f"{p.name} 的必去「{pois[mid].name if mid in pois else mid}」没能排进去")
    # 完全空的方案视为无效(模型可能整体答偏)
    if not any(stops.values()):
        blocking.append("没能排出任何景点")
    return blocking, trimmed, stops


# ------------------------------------------------------------------ 编排
def ai_schedule(
    trip: TripState,
    *,
    start_day: int = 0,
    freeze: dict[int, list[DayStop]] | None = None,
    prior_rows: list[FairnessRow] | None = None,
    max_revise: int = MAX_REVISE,
) -> tuple[dict[int, list[DayStop]], list[str]]:
    """AI 草案 → 守门 → 针对**阻塞问题** ≤N 轮修复。仍失败抛 PlanValidationError。

    非必去项被裁掉(可裁问题)不触发重试 —— 那是正常的行程取舍,由账本记录。
    `prior_rows` 是上一版行程的公平账(重排时传入),用于计算轮换优先权。
    返回 (停留, 被裁掉的说明)。
    """
    provider = get_provider()
    pois = pois_by_id(trip.city)
    # 真实天气(取不到就是空,不影响排程);注入上下文,让 AI 按天气 + 偏好取舍
    weather = fetch_weather_for_trip(trip)
    context = build_context(trip, pois, start_day=start_day, freeze=freeze,
                            prior_rows=prior_rows, weather=weather)

    draft_txt = provider.draft_itinerary(trip, pois, context)
    draft = _parse_draft(draft_txt)
    blocking, trimmed, stops = _validate(trip, pois, draft, start_day=start_day, freeze=freeze)

    rounds = 0
    while blocking and rounds < max_revise:
        draft_txt = provider.revise_itinerary(draft_txt, "\n".join("- " + s for s in blocking), context)
        draft = _parse_draft(draft_txt)
        blocking, trimmed, stops = _validate(trip, pois, draft, start_day=start_day, freeze=freeze)
        rounds += 1

    if blocking:
        # 面向用户的措辞:不要出现"硬约束/尝试次数"这类内部术语(前端会直接展示这句话)
        raise PlanValidationError(
            f"这次没能安排出合适的行程(已试 {rounds + 1} 次)。下面是卡住的地方:", issues=blocking, attempts=rounds + 1
        )
    return stops, trimmed


def assess_soft_rows(
    trip: TripState,
    stops_by_day: dict[int, list[DayStop]],
    pois: dict[str, POI],
) -> dict:
    """让 AI 对**已定稿的行程**自评软偏好达成度;任何失败都降级为「未评估」({})。

    两个刻意的设计:
    - **必须在这里取 provider** —— tests/fakes.py::patch_provider 打的正是
      harness.get_provider;放到别的模块会绕过测试替身打到真 provider。
    - 软偏好自评**不注入 build_context** —— 它是对结果的报告,不是决策输入。
      若注入,模型就能看着自己的评分标准排行程,自评自刷分失去意义。
    """
    if not any(
        p.soft.must or p.soft.want or p.soft.ok or p.soft.refuse
        for p in trip.participants
    ):
        return {}  # 没人声明软偏好,不必打扰模型
    try:
        return get_provider().assess_soft(trip, stops_by_day, vocab_tags()) or {}
    except Exception:
        return {}  # 自评是锦上添花,绝不能影响一份已经合法的行程


def ai_plan(trip: TripState) -> PlanResult:
    """首排:AI 编排 → 守门 → 组装 PlanResult。失败抛错,不写 current_plan。"""
    if not trip.participants:
        raise PlanValidationError("还没有成员偏好,无法生成行程", issues=["participants 为空"])

    from .cost import essentials_total, sync_essentials
    sync_essentials(trip)  # auto 模式先把食宿单价按当前偏好刷成现值

    pois = pois_by_id(trip.city)
    stops, _ = ai_schedule(trip)
    soft_rows = assess_soft_rows(trip, stops, pois)
    hotel = (trip.hotel_lat, trip.hotel_lng)
    ledger, notes = audit_concessions(
        trip.participants, pois, stops, trip.days, trip.total_budget, hotel,
        headcount=len(trip.participants), essentials_total=essentials_total(trip))
    return build_plan(trip, stops, ledger, notes, pois, engine="ai", soft_rows=soft_rows)
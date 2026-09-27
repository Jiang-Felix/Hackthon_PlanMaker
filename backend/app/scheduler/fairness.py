"""公平性 —— 容量感知的公平账本(报告层,非决策层)。

白盒排程引擎已移除,这里不做任何"保证",只回答两个问题:
1. **计算**:这次谁被牺牲了、被牺牲了多少?(见下面的公式)
2. **报告**:让步账本记录"某个未入选的诉求,当初本可被满足却被漏掉"。
3. **注入**:欠账作为「轮换优先权」写进 AI 上下文(见 harness.build_context)。

## 为什么不用「已满足权重 ÷ 声明总权重」

那个口径是给白盒优化器的**相对目标函数** —— 优化器只要求它可比,绝对值无意义。
白盒移除后它被直接当成面向用户的绝对百分比展示,于是:
- 分母含大量物理上排不进的意愿 → 两天行程塞不下 15 个点,却被算成"公平失败";
- 零声明成员(只填了 refuse,很常见)分母为 0 → 判 0% → 被选为"最不满意"。

## 现在的口径(容量感知)

    active = [p for p in participants if d_p > 0]     # d_p = |must|+|want|+|ok| ∩ 本城合法 poi_id
    n      = len(active)
    S      = |{ 已排停留 : 该 poi_id ∈ 至少一位成员的声明 }|   # 有争议的名额
    U      = |已排停留| - S                                  # 无人声明的填充项
    quota  = S / n        (n = 0 → 0)

    owed_p    = min(d_p, quota)                                  # 不可能"应得"超过自己声明的数量
    share_p   = None if owed_p <= 0 else min(1.0, g_p / owed_p)
    deficit_p = max(0, round(owed_p - g_p))                      # 着色依据(整数)

**为什么不是按声明占比(`owed = S·d_p/Σd`)**:那个公式**奖励多声明** —— 一人把整个
目录标成 ok 就抬高 Σd、压低所有人的 owed,而他自己的 g 因覆盖全部停留而趋近 1。
`min(d_p, S/n)` 对多声明免疫:**按人头均分,但不超过你自己要的数量**。

## 两条必须记住的性质

- `share` **不是划分**,可能 >1、不必求和为 100%(一个停留可同时满足两人)。
  → **禁止**用 `mean(share)` 当"综合公平度",那是不同分母的比值求均值,没有意义。
- 粒度上 2 天行程 `S≈4-8`、`quota≈1-3`,**一个名额就摆动 33–50%**,比率做阈值是噪声。
  所以颜色用整数 `deficit`,比率只作文本展示("拿到 3 / 应得 2.0")。
"""

from __future__ import annotations

from ..models import Concession, FairnessReport, FairnessRow, Participant
from .tiers import LEVELS


# ------------------------------------------------------------------ 软偏好归一化
def normalize_soft(
    raw: dict,
    participants: list[Participant],
    vocab_ids: set[str],
) -> dict[str, dict[str, list[str]]]:
    """把 AI 自评结果归一化成 {participant_id: {satisfied, missed, violated, unaccounted}}。

    纯函数,不碰 AI,便于单测。AI 用**位置整数索引**作键(idx),这里转成成员 id。

    **裁决权归 AI,这里的代码只做防伪,不做判断**:
    - 什么算「被照顾到 / 没照顾到 / 被明确违反」由模型判 —— 包括 dietary 约束该算
      哪一级、`must` 层的标签能否算被违反。代码**不再**限定 violated 只针对 refuse 层
      (旧版两头都写死了这个规则:prompt 里一条、`pick("violated", refused)` 一条)。

    确定性代码只拦三类**编造**:
    1. 键必须是范围内整数 —— 越界/非整数丢弃
    2. 标签必须在本城词表内
    3. 标签必须是**该成员自己声明过的** —— 模型不能给没声明过的标签记账

    外加一条互斥:同一标签同时出现在多个列表时按 `violated > satisfied > missed`
    取最重的一个 —— 矛盾答案里藏着的违反不该被"它也说了 satisfied"冲掉。

    **完整性**:遍历的是 `participants` 而不是 `raw` 的键。模型整个漏掉一位成员时,
    这位成员的标签会落进 `unaccounted`,而不是连人带标签一起消失。`raw` 整体不是 dict
    (调用失败)才返回 `{}` —— 那是真的「未评估」。
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, list[str]]] = {}
    for idx, p in enumerate(participants):
        declared = [t for lv in ("refuse", "must", "want", "ok") for t in getattr(p.soft, lv)]
        if not declared:
            continue                      # 没声明软偏好的人不生成条目
        val = raw.get(str(idx), raw.get(idx))
        if not isinstance(val, dict):
            val = {}

        def pick(field: str) -> list[str]:
            items = val.get(field) or []
            if not isinstance(items, list):
                return []
            seen: set[str] = set()
            keep: list[str] = []
            for t in items:
                t = str(t)
                if t in vocab_ids and t in declared and t not in seen:
                    seen.add(t)
                    keep.append(t)
            return keep

        violated = pick("violated")
        satisfied = [t for t in pick("satisfied") if t not in violated]
        missed = [t for t in pick("missed") if t not in violated and t not in satisfied]
        judged = set(violated) | set(satisfied) | set(missed)
        # 去重保序:declared 里同一标签可能被填进多个层级
        unaccounted = [t for i, t in enumerate(declared) if t not in judged and t not in declared[:i]]
        out[p.id] = {"satisfied": satisfied, "missed": missed,
                     "violated": violated, "unaccounted": unaccounted}
    return out


# ------------------------------------------------------------------ 单人账
def fairness_row(
    p: Participant,
    *,
    declared: set[str],
    included: set[str],
    quota: float,
    concessions: list[Concession],
    soft: dict[str, list[str]],
) -> FairnessRow:
    """汇总一个人的公平账。`declared` 已按本城合法 POI 过滤。"""
    got = len(declared & included)
    owed = min(float(len(declared)), quota)
    share = None if owed <= 0 else min(1.0, got / owed)
    # round-half-up:Python 内置 round() 是银行家舍入,round(0.5)==0 会低估缺口
    deficit = max(0, int(owed - got + 0.5))

    satisfied: dict[str, list[str]] = {lv: [] for lv in LEVELS}
    missing: dict[str, list[str]] = {lv: [] for lv in LEVELS}
    for lv in LEVELS:
        for pid in getattr(p.pref, lv):
            if pid not in declared:
                continue
            (satisfied if pid in included else missing)[lv].append(pid)

    soft_sat = list(soft.get("satisfied", []))
    soft_missed = list(soft.get("missed", []))
    soft_violated = list(soft.get("violated", []))
    soft_unaccounted = list(soft.get("unaccounted", []))
    # 分母是**拿到裁决的**数量(三类之和),不是声明数 —— 模型漏答的标签只进
    # soft_unaccounted,不能拉低达成率(否则"没评估"会被算成"没做到")。
    soft_cared = len(soft_sat) + len(soft_missed) + len(soft_violated)
    # ⚠️ 四个层级都要数:`refuse` 也是声明。只数 must/want/ok 的话,一个只声明了
    # 「不吃辣」的人 soft_declared==0 → 前端整块软偏好不渲染 → 声明彻底不可见。
    soft_declared = sum(len(getattr(p.soft, lv)) for lv in ("refuse", "must", "want", "ok"))
    return FairnessRow(
        participant_id=p.id,
        name=p.name,
        must_met=len(satisfied["must"]),
        must_total=len(satisfied["must"]) + len(missing["must"]),
        slots_got=got,
        wants_declared=len(declared),
        slots_owed=owed,
        share=share,
        deficit=deficit,
        soft_declared=soft_declared,
        soft_cared=soft_cared,
        # 未评估 ≠ 未满足:分母为 0 时必须落 None,绝不能是 0(那会让"AI 没评估"
        # 显示成"你的偏好全没被照顾")。
        soft_rate=(len(soft_sat) / soft_cared) if soft_cared else None,
        soft_satisfied=soft_sat,
        soft_missed=soft_missed,
        soft_violated=soft_violated,
        soft_unaccounted=soft_unaccounted,
        satisfied=satisfied,
        missing=missing,
        concession_count=sum(1 for c in concessions if c.participant_id == p.id),
    )


def build_fairness_report(
    participants: list[Participant],
    stops_by_day: dict[int, list],
    concessions: list[Concession],
    *,
    soft_rows: dict[str, dict[str, list[str]]] | None = None,
    valid_ids: set[str] | None = None,
) -> FairnessReport:
    """容量感知的公平报告。`valid_ids` 用于过滤非法 poi_id(不给就不过滤)。"""
    included = {s.poi_id for stops in stops_by_day.values() for s in stops}
    soft_rows = soft_rows or {}

    declared: dict[str, set[str]] = {}
    for p in participants:
        ids = {pid for lv in LEVELS for pid in getattr(p.pref, lv)}
        if valid_ids is not None:
            ids &= valid_ids
        declared[p.id] = ids

    contested = {pid for pid in included if any(pid in d for d in declared.values())}
    undeclared = len(included) - len(contested)
    active = [p for p in participants if declared[p.id]]
    quota = (len(contested) / len(active)) if active else 0.0

    rows = [
        fairness_row(
            p,
            declared=declared[p.id],
            included=included,
            quota=quota,
            concessions=concessions,
            soft=soft_rows.get(p.id, {}),
        )
        for p in participants
    ]
    return FairnessReport(
        participants=rows,
        concessions=concessions,
        summary_messages=summarize(rows, len(contested), undeclared, quota, len(active)),
        contested_slots=len(contested),
        undeclared_slots=undeclared,
        quota=round(quota, 2),
    )


def summarize(
    rows: list[FairnessRow],
    contested: int,
    undeclared: int,
    quota: float,
    active_count: int,
) -> list[str]:
    """一句话总结(供前端公平面板与讲解用)。

    注意:`share is None` 的行(零声明成员)**完全排除**出 best/worst —— 没提要求
    不等于极度不满,旧版把它们选为"最不满意"正是要修的缺陷之一。
    """
    if not rows:
        return ["还没有成员。"]
    msgs: list[str] = []
    if active_count:
        msgs.append(f"本次共 {contested} 个有人想要的停留,{active_count} 人均分 {quota:.1f} 个。")
    else:
        msgs.append("还没有人提出意愿,无法计算名额分配。")

    scored = [r for r in rows if r.share is not None]
    if scored:
        worst = max(scored, key=lambda r: (r.deficit, -r.share))
        if worst.deficit >= 1:
            msgs.append(
                f"{worst.name} 本轮少拿到 {worst.deficit} 个名额"
                f"(拿到 {worst.slots_got} / 应得 {worst.slots_owed:.1f}),建议下次优先照顾 TA 的诉求"
            )
        else:
            # 措辞必须**限定在名额分配**上:这一整段只算了 deficit,一个字都没算软偏好。
            # 写成光秃秃的"每个人都拿到了应得的份额",会和下面某人 0% 的软偏好条并排出现,
            # 读起来像"大家都挺好" —— 与本次重做要消灭的假话同源。
            msgs.append("名额分配上,每个人都拿到了应得的份额。")

    for r in rows:
        if r.must_total and r.must_met < r.must_total:
            msgs.append(f"{r.name} 有 {r.must_total - r.must_met} 个『必去』未满足")
        if r.soft_violated:
            msgs.append(f"{r.name} 明确表示不接受的偏好被违反了 {len(r.soft_violated)} 项")
        elif r.soft_cared and not r.soft_satisfied:
            # 评估过了、且一项都没命中 —— 这正是"名额拿到了,但体验没照顾到"的情形,
            # 不说出来的话,上面那句"名额分配上…"就成了整页唯一的结论。
            msgs.append(f"{r.name} 声明的软偏好一项都没被照顾到(共 {r.soft_cared} 项),下次请一并考虑")
        if r.soft_unaccounted:
            # 独立于上面两条:这是**覆盖度**声明,不是严重程度声明,可以和违反同时成立。
            # 沉默会让"声明了不吃辣"在页面上什么都不显示。
            msgs.append(f"{r.name} 有 {len(r.soft_unaccounted)} 项软偏好未获评估,本次结论不含这几项")

    if undeclared:
        msgs.append(f"本次有 {undeclared} 个安排不在任何人的意愿清单内。")
    return msgs

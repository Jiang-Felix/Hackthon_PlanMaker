"""公平性测试:权重分层、容量感知的公平口径、防平均主义的**校验**落点。

注意:移除白盒引擎后,"防平均主义/轮换涌现"不再由优化器*保证*,而是靠
「prompt 决策宪法 + must 覆盖率校验」双轨。因此这里验证的是:
- 新公平口径的数学(纯函数)
- 校验器确实会拦住"丢掉某人必去"的草案(硬地板)

⚠️ 本文件里有若干用例是**回归护栏**:它们对应本次修掉的缺陷(容量盲分母、
零声明成员被判 0%、多声明者抬高门槛)。删掉它们,缺陷就会悄悄回来。
"""

from __future__ import annotations

from app.data.loader import pois_by_id
from app.models import DayStop
from app.scheduler.fairness import build_fairness_report, normalize_soft
from app.scheduler.harness import _validate, ai_plan
from app.scheduler.tiers import WEIGHT
from tests.conftest import make_participant
from tests.fakes import FakeProvider, draft, patch_provider


def _stops(*ids: str) -> dict[int, list[DayStop]]:
    """把一串 poi_id 塞进第 0 天(只关心"排进去了哪些",不关心时间)。"""
    return {0: [DayStop(poi_id=i, name=i, arrive_min=540, start_min=540, end_min=600)
                for i in ids]}


def test_tier_weights_must_dominates_ok():
    """WEIGHT 仍用于「哪个层级更优先」的排序与解释(explanation.py)。"""
    assert WEIGHT["must"] == 10.0
    assert WEIGHT["want"] == 4.0
    assert WEIGHT["ok"] == 1.0
    assert WEIGHT["must"] > 3 * WEIGHT["ok"]  # 1 个必去 > 3 个可接受


# ---------------------------------------------------------------- 容量感知口径
def test_quota_is_per_head_and_capped_by_own_declarations():
    """按人头均分,但不超过自己声明的数量。

    ★ 回归护栏:旧口径 `owed = S·d/Σd` 会被**多声明者**污染 ——
    B 声明 20 个会把 A(只声明 1 个)的 owed 压到 0.19,让 A 拿 1 个就显示 525%。
    """
    alice = make_participant("A", must=["sh02"])
    bob = make_participant("B", ok=[f"sh{i:02d}" for i in range(5, 25)])
    valid = {f"sh{i:02d}" for i in range(1, 26)}
    report = build_fairness_report([alice, bob], _stops("sh02", "sh05", "sh06", "sh07"),
                                   [], valid_ids=valid)
    rows = {r.name: r for r in report.participants}

    assert report.contested_slots == 4
    assert report.quota == 2.0
    # A 只声明 1 个 → owed 封顶在 1,不会被 B 的声明量稀释
    assert rows["A"].slots_owed == 1.0
    assert rows["A"].slots_got == 1
    assert rows["A"].share == 1.0
    assert rows["A"].deficit == 0
    # B 的 owed 封顶在 quota=2,不会因为声明多就"应得"更多
    assert rows["B"].slots_owed == 2.0


def test_zero_declaration_member_is_na_not_zero():
    """★ 回归护栏:只填了 refuse 的成员必须落 N/A,不能被选成"最不满意"。

    旧实现 denom<=0 时返回 0.0,于是 summarize 把它选为 worst,前端显示
    "满意度仅 0%,建议下次优先安排 TA 的诉求" —— 没提要求 ≠ 极度不满。
    """
    alice = make_participant("A", must=["sh02"])
    carol = make_participant("C", refuse=["sh05"])   # 只表了态"不想去",没提任何想去
    report = build_fairness_report([alice, carol], _stops("sh02"), [],
                                   valid_ids={"sh02", "sh05"})
    rows = {r.name: r for r in report.participants}

    assert rows["C"].wants_declared == 0
    assert rows["C"].share is None
    assert rows["C"].slots_owed == 0
    assert not any("C" in m and "0%" in m for m in report.summary_messages)
    # C 不该被当成"被牺牲的人"
    assert not any("优先照顾" in m and "C" in m for m in report.summary_messages)


def test_deficit_is_integer_and_flags_the_shortchanged():
    """★ 缺口用整数:粒度只有几个名额,比率在阈值上是噪声。"""
    a = make_participant("A", must=["sh02"], want=["sh05", "sh06", "sh07"])
    b = make_participant("B", must=["sh08"], want=["sh09", "sh10", "sh11"])
    valid = {f"sh{i:02d}" for i in range(1, 26)}
    # 只排了 A 的 1 个、B 的 3 个
    report = build_fairness_report([a, b], _stops("sh02", "sh08", "sh09", "sh10"), [],
                                   valid_ids=valid)
    rows = {r.name: r for r in report.participants}

    assert report.quota == 2.0
    assert isinstance(rows["A"].deficit, int)
    assert rows["A"].slots_got == 1 and rows["A"].slots_owed == 2.0
    assert rows["A"].deficit == 1          # 拿到 1 / 应得 2 → 欠 1
    assert any("A" in m and "少拿到 1 个名额" in m for m in report.summary_messages)


def test_all_served_says_so():
    """全员达标时,必须能说出一句正面的话(旧实现永远说不出)。

    注意措辞限定在「名额分配」上 —— 这句只算了 deficit,一个字都没算软偏好
    (见 `test_slots_all_met_but_soft_all_missed_is_called_out`)。
    """
    a = make_participant("A", must=["sh02"], want=["sh05"])
    report = build_fairness_report([a], _stops("sh02", "sh05"), [], valid_ids={"sh02", "sh05"})
    assert any("名额分配上" in m and "每个人都拿到了应得的份额" in m
               for m in report.summary_messages)


def test_empty_contested_pool_does_not_divide_by_zero():
    """★ 排进去的全是没人声明的 → S=0,不能除零,也不能算成"谁被牺牲了"。"""
    a = make_participant("A", must=["sh02"])
    report = build_fairness_report([a], _stops("sh99"), [], valid_ids={"sh02", "sh99"})
    assert report.contested_slots == 0
    assert report.undeclared_slots == 1
    assert report.quota == 0.0
    assert report.participants[0].share is None
    assert any("不在任何人的意愿清单内" in m for m in report.summary_messages)


def test_no_participants_declaring_anything():
    """没有任何人提出意愿 → 不炸,全部 N/A。"""
    a = make_participant("A", refuse=["sh02"])
    report = build_fairness_report([a], _stops("sh05"), [], valid_ids={"sh02", "sh05"})
    assert report.quota == 0.0
    assert report.participants[0].share is None
    assert any("还没有人提出意愿" in m for m in report.summary_messages)


def test_invalid_poi_ids_are_excluded_from_denominator():
    """★ replan 路径把 structured 直接写进 pref、不过 hydrate,非法 id 会进分母。"""
    a = make_participant("A", must=["sh02"], want=["不存在的id", "另一个假id"])
    report = build_fairness_report([a], _stops("sh02"), [], valid_ids={"sh02", "sh05"})
    assert report.participants[0].wants_declared == 1   # 只算合法的那个


# ---------------------------------------------------------------- 软偏好
def test_soft_not_assessed_is_none_not_zero():
    """★ 回归护栏:未评估 ≠ 未满足。

    模型耍懒/自评失败必须落 None —— 落 0 就是"AI 没评估"显示成"你的偏好全没被照顾",
    等于把零声明成员那个缺陷在软偏好这一列重演一遍。
    """
    a = make_participant("A", must=["sh02"], soft={"must": ["en_light"]})
    report = build_fairness_report([a], _stops("sh02"), [], valid_ids={"sh02"})
    row = report.participants[0]
    assert row.soft_declared == 1
    assert row.soft_cared == 0
    assert row.soft_rate is None
    # 未评估也不能被说成"一项都没被照顾到"
    assert not any("软偏好" in m for m in report.summary_messages)


def test_slots_all_met_but_soft_all_missed_is_called_out():
    """★ 回归护栏:「名额分配上…」不能成为整页唯一的结论。

    实测(真实模型,2026-09-27):某成员 2 个名额全拿到、deficit=0,但声明的软偏好
    一条没命中(soft_rate=0.0)。此时总结里只有一句"每个人都拿到了应得的份额。",
    和下面 0% 的软偏好条并排,读起来像"大家都挺好"。
    """
    a = make_participant("A", must=["sh02"], soft={"must": ["di_mild"]})
    report = build_fairness_report(
        [a], _stops("sh02"), [],
        soft_rows={a.id: {"satisfied": [], "missed": ["di_mild"], "violated": []}},
        valid_ids={"sh02"},
    )
    row = report.participants[0]
    assert row.share == 1.0 and row.deficit == 0        # 名额层面确实没亏待
    assert any("软偏好一项都没被照顾到" in m for m in report.summary_messages)
    # 而那句总结仍然只主张名额分配,不越界
    assert any("名额分配上" in m for m in report.summary_messages)


def test_soft_all_satisfied_does_not_warn():
    """全命中时不要刷屏。"""
    a = make_participant("A", must=["sh02"], soft={"must": ["di_mild"]})
    report = build_fairness_report(
        [a], _stops("sh02"), [],
        soft_rows={a.id: {"satisfied": ["di_mild"], "missed": [], "violated": []}},
        valid_ids={"sh02"},
    )
    assert not any("软偏好" in m for m in report.summary_messages)


def test_soft_assessment_is_reported():
    a = make_participant("A", must=["sh02"], soft={"must": ["en_light"], "want": ["w_rain_no"]})
    report = build_fairness_report(
        [a], _stops("sh02"), [],
        soft_rows={a.id: {"satisfied": ["en_light"], "missed": ["w_rain_no"], "violated": []}},
        valid_ids={"sh02"},
    )
    row = report.participants[0]
    assert row.soft_cared == 2
    assert row.soft_rate == 0.5
    assert row.soft_satisfied == ["en_light"]
    assert row.soft_missed == ["w_rain_no"]


def test_soft_violation_is_surfaced():
    """软 refuse 被违反必须在总结里点名(硬 refuse 由守门层管,软的口径只在这里)。

    注意 `di_mild` = **不吃辣**(该落在 refuse),别写成 `di_spicy` = 能吃辣 —— 语义反了。
    """
    a = make_participant("A", must=["sh02"], soft={"refuse": ["di_mild"]})
    report = build_fairness_report(
        [a], _stops("sh02"), [],
        soft_rows={a.id: {"satisfied": [], "missed": [], "violated": ["di_mild"]}},
        valid_ids={"sh02"},
    )
    assert report.participants[0].soft_violated == ["di_mild"]
    assert any("不接受" in m for m in report.summary_messages)


def test_normalize_soft_filters_keys_vocab_and_undeclared_tags():
    """归一化的三道过滤:键越界 / 非词表标签 / 该成员没声明过的标签,一律丢弃。

    (`di_mild` = 不吃辣,才是能落在 refuse 的那个;`di_spicy` = 能吃辣。)
    """
    a = make_participant("A", soft={"must": ["en_light"], "want": ["w_rain_no"],
                                    "refuse": ["di_mild"]})
    raw = {
        "0": {"satisfied": ["en_light", "编造标签"], "missed": ["en_light", "w_rain_no"],
              "violated": ["di_mild"]},
        "9": {"satisfied": ["en_light"]},          # 越界索引 → 丢
        "x": {"satisfied": ["en_light"]},          # 非整数键 → 丢
    }
    out = normalize_soft(raw, [a], {"en_light", "w_rain_no", "di_mild"})
    assert out[a.id]["satisfied"] == ["en_light"]           # 编造标签被丢
    assert out[a.id]["missed"] == ["w_rain_no"]             # 与 satisfied 重复的被去重
    assert out[a.id]["violated"] == ["di_mild"]


def test_normalize_soft_rejects_garbage():
    """调用整体失败(不是 dict)→ `{}`,即真正的「未评估」。

    而 `{"0": "也不是字典"}` 是**答了但答废了** —— 该成员的标签落进 `unaccounted`,
    不返回 `{}`:这两者必须可区分,前者是"没问",后者是"问了没答"。
    """
    a = make_participant("A", soft={"must": ["en_light"]})
    for garbage in (None, "不是字典", 42, []):
        assert normalize_soft(garbage, [a], {"en_light"}) == {}

    out = normalize_soft({"0": "也不是字典"}, [a], {"en_light"})
    assert out[a.id]["unaccounted"] == ["en_light"]
    assert out[a.id]["satisfied"] == []


def test_normalize_soft_only_accepts_own_declared_tags():
    """模型不能给没声明过的标签记账(防止瞎猜 satisfied)。

    编造标签被丢掉后,该成员**真正声明过的**那条就变成未获评估 —— 而不是连人带标签
    一起消失(那正是"声明了不吃辣"在页面上什么都不显示的原因)。
    """
    a = make_participant("A", soft={"must": ["en_light"]})
    out = normalize_soft({"0": {"satisfied": ["rh_late"]}}, [a], {"en_light", "rh_late"})
    assert out[a.id]["satisfied"] == []                  # 编造的 tag 不被采信
    assert out[a.id]["unaccounted"] == ["en_light"]      # 真正声明的那条要如实报出


def test_normalize_soft_emits_all_participants_including_skipped_ones():
    """★ 回归护栏:模型整个漏掉一位成员时,这位成员不能连人带标签一起消失。

    旧实现遍历的是 AI 返回的键 —— 模型只回 `"0"` 时,成员 1 直接不存在,页面上
    什么都看不到。现在遍历 `participants`,漏掉的成员落 `unaccounted`。
    """
    a = make_participant("A", soft={"must": ["en_light"]})
    b = make_participant("B", soft={"refuse": ["di_mild"]})
    out = normalize_soft({"0": {"satisfied": ["en_light"]}}, [a, b], {"en_light", "di_mild"})
    assert out[a.id]["satisfied"] == ["en_light"]
    assert out[b.id]["unaccounted"] == ["di_mild"]


def test_normalize_soft_violated_beats_contradictory_answers():
    """同一标签被同时判为 violated 和 satisfied 时取 violated。

    矛盾答案里藏着的那条违反,不该被"它也说了 satisfied"冲掉。
    """
    a = make_participant("A", soft={"must": ["di_mild"]})
    out = normalize_soft(
        {"0": {"satisfied": ["di_mild"], "violated": ["di_mild"]}}, [a], {"di_mild"})
    assert out[a.id]["violated"] == ["di_mild"]
    assert out[a.id]["satisfied"] == []
    assert out[a.id]["unaccounted"] == []


def test_normalize_soft_violated_is_not_limited_to_refuse_tier():
    """★ 裁决权归 AI:violated 不再限定 refuse 层。

    旧版两头都写死「violated 仅针对 refuse 类标签」(prompt 一条 + `pick(..., refused)` 一条),
    于是「不吃辣」被 NL 解析放进 must 层时,违反**永远**查不出来。
    """
    a = make_participant("A", soft={"must": ["di_mild"]})   # 注意:在 must 层
    out = normalize_soft({"0": {"violated": ["di_mild"]}}, [a], {"di_mild"})
    assert out[a.id]["violated"] == ["di_mild"]


# ---------------------------------------------------------------- 守门 / 端到端
def test_validator_rejects_diluting_must(shanghai, make_trip):
    """委员会第2条:A 的『必去』被 B 的 5 个普通偏好挤掉 → 校验器必须拦下。"""
    alice = make_participant("A", must=["sh02"])
    bob = make_participant("B", ok=["sh05", "sh06", "sh10", "sh18", "sh20"])
    trip = make_trip(participants=[alice, bob])
    pois = pois_by_id("shanghai")

    blocking, _, _ = _validate(trip, pois, {0: ["sh05", "sh06", "sh10", "sh18", "sh20"]})
    assert any("必去" in i and "A" in i for i in blocking)


def test_ai_plan_covers_all_musts(shanghai, make_trip, monkeypatch):
    """两人必去都可纳入时,双方都必须被覆盖。"""
    alice = make_participant("A", must=["sh02"])
    bob = make_participant("B", must=["sh12"])
    trip = make_trip(days=2, budget=2500, participants=[alice, bob])  # 门票按人数×2,预算给足
    patch_provider(monkeypatch, FakeProvider(draft(["sh12"], ["sh02"])))

    plan = ai_plan(trip)
    rows = {r.name: r for r in plan.fairness.participants}
    assert rows["A"].must_met == 1
    assert rows["B"].must_met == 1


def test_fairness_report_reflects_ai_output(shanghai, make_trip, monkeypatch):
    """公平账本是**报告**:如实反映 AI 产出的名额分配,而不是优化目标。"""
    alice = make_participant("A", must=["sh02"], ok=["sh05"])
    bob = make_participant("B", must=["sh07"])
    trip = make_trip(days=2, budget=1200, participants=[alice, bob])
    patch_provider(monkeypatch, FakeProvider(draft(["sh02"], ["sh07"])))

    plan = ai_plan(trip)
    rows = {r.name: r for r in plan.fairness.participants}
    # A 声明 2 个(must sh02 + ok sh05),命中 1 个;两人均分 S=2 → quota=1
    assert rows["A"].wants_declared == 2
    assert rows["A"].slots_got == 1
    assert rows["A"].slots_owed == 1.0
    assert rows["A"].deficit == 0        # 拿到 1 / 应得 1 → 没被牺牲
    assert rows["B"].slots_got == 1
    assert rows["B"].share == 1.0
    assert rows["A"].must_met == 1 and rows["B"].must_met == 1

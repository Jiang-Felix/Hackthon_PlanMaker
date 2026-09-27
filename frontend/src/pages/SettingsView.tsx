import { useEffect, useState } from "react";
import { api } from "../api/client";
import ReplanDiff from "../components/ReplanDiff";
import { fmtStartAt, tripTimeState } from "../time";
import { Plan, PreferenceVocab, RecoSettings, ReplanResult, Trip } from "../types";

/**
 * 全局「推荐设置」页(评审 Recommendation Logic Design)。
 *
 * 分类型控件:单选 / 有序优先级 / 数值;并支持「一句话让 AI 帮我设」。
 * 所有改动即时持久化到服务端(TripState.settings),因此切换页面不丢信息。
 *
 * 行程「已开始」后,底部主按钮从「生成行程」变「更新行程」:冻结已过期的天,
 * 只重排剩余天,并内联展示换入/换出 diff(原「动态调整」页功能并入本页)。
 */
const DEFAULT: RecoSettings = {
  conflict_strategy: "rotate",
  schedule_align: "fill",
  activity_priorities: [],
  buffer_min: 15,
  max_wait_min: 30,
  raw_text: "",
};

interface Props {
  trip: Trip;
  onUpdated: () => Promise<void>;
  /** 生成/重新生成行程(未开始,走全量生成) */
  onPlanReady: () => void;
  /** 跳去「行程」tab 看最新路线 */
  onOpenPlan: () => void;
}

export default function SettingsView({ trip, onUpdated, onPlanReady, onOpenPlan }: Props) {
  const [vocab, setVocab] = useState<PreferenceVocab | null>(null);
  const [s, setS] = useState<RecoSettings>(trip.settings ?? DEFAULT);
  const [nl, setNl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 最近一次「更新行程」的结果(已开始状态下才出现)
  const [lastUpdate, setLastUpdate] = useState<{ result: ReplanResult; oldPlan: Plan | null } | null>(null);
  // 食宿预算(规则页可选项):auto=按偏好估计 / manual=手动单价
  const [bmode, setBmode] = useState<"auto" | "manual">(trip.budget_mode ?? "auto");
  const [bfood, setBfood] = useState<number>(trip.food_per_head ?? 90);
  const [blodge, setBlodge] = useState<number>(trip.lodging_per_head ?? 180);

  useEffect(() => {
    api.getVocab().then(setVocab).catch(() => {});
  }, []);
  useEffect(() => {
    setS(trip.settings ?? DEFAULT);
  }, [trip.settings]);
  useEffect(() => {
    setLastUpdate(null); // 换了行程,旧 diff 清空
  }, [trip.id]);
  useEffect(() => {
    setBmode(trip.budget_mode ?? "auto");
    setBfood(trip.food_per_head ?? 90);
    setBlodge(trip.lodging_per_head ?? 180);
  }, [trip.budget_mode, trip.food_per_head, trip.lodging_per_head]);

  const saveBudget = async (next: {
    mode?: "auto" | "manual";
    food_per_head?: number;
    lodging_per_head?: number;
  }) => {
    setBusy(true);
    setErr(null);
    try {
      await api.saveBudget(trip.id, next);
      await onUpdated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const save = async (next: RecoSettings) => {
    setS(next);
    setBusy(true);
    setErr(null);
    try {
      await api.saveSettings(trip.id, { settings: next });
      await onUpdated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const parse = async () => {
    if (!nl.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const t = await api.saveSettings(trip.id, { natural_text: nl });
      setS(t.settings);
      setNl("");
      await onUpdated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  /** 已开始状态下的「更新行程」:不指定 member/current_day,后端按 start_at 自动冻结并重排剩余天 */
  const update = async () => {
    setBusy(true);
    setErr(null);
    const oldPlan = trip.current_plan; // 更新前的旧计划(给「换出」查名字)
    try {
      const res = await api.replan(trip.id, {});
      setLastUpdate({ result: res, oldPlan });
      await onUpdated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const timeState = tripTimeState(trip);
  const hasPlan = !!trip.current_plan;
  const needUpdate = hasPlan && timeState.started; // 有行程且已开始 → 主按钮 = 更新行程
  const mainLabel = needUpdate ? "更新行程 🔄" : hasPlan ? "重新生成" : "生成行程 🧭";
  const mainAction = needUpdate ? update : onPlanReady;

  const opts = vocab?.reco_options;
  const prioOptions = opts?.activity_priorities ?? [];

  const togglePrio = (id: string) => {
    const cur = s.activity_priorities;
    save({
      ...s,
      activity_priorities: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    });
  };
  const movePrio = (i: number, delta: number) => {
    const list = [...s.activity_priorities];
    const j = i + delta;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    save({ ...s, activity_priorities: list });
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>📐 全局规则</h2>
        <p className="muted">
          这些是**全队层面**的排程规则,会作为有效条件交给 AI 决策端。
          <b>已有一套默认值 —— 不自定义也可以直接生成行程。</b>改动即时保存,切换页面不会丢失。
        </p>
      </div>

      {timeState.started && (
        <div className="banner mode-banner">
          {timeState.current_day === 0
            ? "🟢 行程已开始,正在第 1 天"
            : `🧊 行程已开始 · 前 ${timeState.current_day} 天已冻结 · 今天是第 ${timeState.current_day + 1} 天`}
          <div className="muted small">
            已过期的天随墙钟自动冻结;底部「更新行程」只重排剩余天
          </div>
        </div>
      )}

      {err && <div className="error-banner">⚠️ {err}</div>}

      <div className="card">
        <label className="field-label">一句话让 AI 帮我设(可选)</label>
        <textarea
          className="nl-input"
          rows={2}
          placeholder="例:尽量别安排重复的同类活动,每天别太赶,留白 20 分钟"
          value={nl}
          onChange={(e) => setNl(e.target.value)}
        />
        <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }} disabled={busy || !nl.trim()} onClick={parse}>
          ✨ AI 帮我理解并填入
        </button>
      </div>

      <div className="card">
        <label className="field-label">冲突解决</label>
        <div className="pill-row">
          {(opts?.conflict_strategy ?? []).map((o) => (
            <button
              key={o.id}
              className={`tier-pill ${s.conflict_strategy === o.id ? "active" : ""}`}
              onClick={() => save({ ...s, conflict_strategy: o.id as RecoSettings["conflict_strategy"] })}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p className="muted small">当成员诉求冲突时的取舍策略(由 AI 据此安排,不额外强制结构)。</p>
      </div>

      <div className="card">
        <label className="field-label">日程对齐</label>
        <div className="pill-row">
          {(opts?.schedule_align ?? []).map((o) => (
            <button
              key={o.id}
              className={`tier-pill ${s.schedule_align === o.id ? "active" : ""}`}
              onClick={() => save({ ...s, schedule_align: o.id as RecoSettings["schedule_align"] })}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p className="muted small">左对齐=尽量早结束;填充=每天都排满活动。</p>
      </div>

      <div className="card">
        <label className="field-label">活动关联优先级(点选 + 排序)</label>
        <div className="pill-row">
          {prioOptions.map((o) => (
            <button
              key={o.id}
              className={`tier-pill ${s.activity_priorities.includes(o.id) ? "active" : ""}`}
              onClick={() => togglePrio(o.id)}
            >
              {s.activity_priorities.includes(o.id) ? "✓ " : ""}
              {o.label}
            </button>
          ))}
        </div>
        {s.activity_priorities.length > 0 && (
          <ul className="rb-rows" style={{ marginTop: 10 }}>
            {s.activity_priorities.map((id, i) => {
              const label = prioOptions.find((o) => o.id === id)?.label ?? id;
              return (
                <li key={id} className="rb-row">
                  <span className="rb-rank">#{i + 1}</span>
                  <span className="rb-row-name">{label}</span>
                  <span className="rb-row-tools">
                    <button className="rb-row-btn" disabled={i === 0} onClick={() => movePrio(i, -1)}>↑</button>
                    <button className="rb-row-btn" disabled={i === s.activity_priorities.length - 1} onClick={() => movePrio(i, 1)}>↓</button>
                    <button className="rb-row-btn del" onClick={() => togglePrio(id)}>✕</button>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="card">
        <label className="field-label">景点间留白:{s.buffer_min} 分钟</label>
        <input
          type="range" min={0} max={90} step={5} value={s.buffer_min}
          onChange={(e) => setS({ ...s, buffer_min: Number(e.target.value) })}
          onMouseUp={() => save(s)}
          onTouchEnd={() => save(s)}
        />
        <label className="field-label">排队等待上限:{s.max_wait_min} 分钟</label>
        <input
          type="range" min={0} max={120} step={5} value={s.max_wait_min}
          onChange={(e) => setS({ ...s, max_wait_min: Number(e.target.value) })}
          onMouseUp={() => save(s)}
          onTouchEnd={() => save(s)}
        />
      </div>

      {s.raw_text && <p className="muted small">上次 AI 解析的原文:{s.raw_text}</p>}
      {busy && <div className="muted small">保存中…</div>}

      {/* 食宿预算(评审经济计算):自动按偏好估计 / 手动填单价 */}
      <section className="card budget-card">
        <h3>🍽️ 食宿预算</h3>
        <p className="muted small">
          总预算是<b>全队合计</b>。门票按<b>每人</b>计(×{trip.participants.length} 人),
          打车全队共享一趟;食宿先扣掉,门票+交通在剩余预算里排。
        </p>
        <div className="seg">
          <button className={bmode === "auto" ? "active" : ""} onClick={() => saveBudget({ mode: "auto" })}>
            🤖 自动(按偏好)
          </button>
          <button className={bmode === "manual" ? "active" : ""} onClick={() => saveBudget({ mode: "manual" })}>
            ✋ 手动
          </button>
        </div>
        {bmode === "auto" ? (
          <p className="muted small">
            按成员消费/住宿偏好估计:<b>餐 ¥{(trip.food_per_head ?? 0).toFixed(0)}</b>/人/天 ·
            <b> 宿 ¥{(trip.lodging_per_head ?? 0).toFixed(0)}</b>/人/晚 —— 全队{" "}
            {trip.participants.length} 人 × {trip.days} 天 ={" "}
            <b>¥{((trip.food_per_head ?? 0) + (trip.lodging_per_head ?? 0)) * trip.participants.length * trip.days}</b>
          </p>
        ) : (
          <div className="budget-inputs">
            <label className="field-label">每人每天餐费 ¥</label>
            <input type="number" className="field" value={bfood} onChange={(e) => setBfood(Number(e.target.value))} />
            <label className="field-label">每人每晚住宿 ¥</label>
            <input type="number" className="field" value={blodge} onChange={(e) => setBlodge(Number(e.target.value))} />
            <button
              className="btn btn-primary btn-sm"
              disabled={busy}
              onClick={() => saveBudget({ mode: "manual", food_per_head: bfood, lodging_per_head: blodge })}
            >
              保存食宿单价
            </button>
          </div>
        )}
      </section>

      {lastUpdate && (
        <div className="card">
          <ReplanDiff result={lastUpdate.result} oldPlan={lastUpdate.oldPlan} />
          <button className="btn btn-ghost btn-lg" style={{ marginTop: 10 }} onClick={onOpenPlan}>
            查看最新行程 →
          </button>
        </div>
      )}

      <div className="sticky-actions">
        {trip.participants.length === 0 && (
          <div className="hint-bar">👆 还没有成员偏好 —— 先回「偏好」页添加成员,再生成行程</div>
        )}
        <button
          className="btn btn-primary btn-lg"
          disabled={trip.participants.length === 0}
          onClick={mainAction}
        >
          {busy ? (needUpdate ? "更新中…" : "生成中…") : mainLabel}
          <span className="gen-count">
            {needUpdate
              ? `已冻结 ${timeState.current_day} 天 · ${fmtStartAt(trip) || ""}`
              : trip.participants.length > 0
                ? `${trip.participants.length} 位成员`
                : ""}
          </span>
        </button>
      </div>
    </div>
  );
}
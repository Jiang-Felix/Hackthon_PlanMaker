import { useState } from "react";
import { api } from "../api/client";
import CityPicker from "../components/CityPicker";
import { CITY_META, Trip } from "../types";

const DAYS_MIN = 1;
const DAYS_MAX = 7; // 与后端 TripCreate.days 的约束一致
const PEOPLE_MIN = 1;
const PEOPLE_MAX = 8; // 与后端 TripCreate.initial_people 的约束一致
const BUDGET_MIN = 100;
const BUDGET_MAX = 20000;

function zero(n: number) {
  return String(n).padStart(2, "0");
}
function isoDate(d: Date) {
  return `${d.getFullYear()}-${zero(d.getMonth() + 1)}-${zero(d.getDate())}`;
}
function isoTime(d: Date) {
  return `${zero(d.getHours())}:${zero(d.getMinutes())}`;
}

/** 默认出发时间:下一整点(方便立刻演示「已开始」) */
function defaultStart() {
  const d = new Date();
  d.setHours(d.getHours() + 1, 0, 0, 0);
  return { date: isoDate(d), time: isoTime(d) };
}

/** 可调数值控件:− / 值 / ＋,带上下限。 */
function NumStepper({
  value,
  onChange,
  min,
  max,
  step = 1,
  render,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  render?: (v: number) => string;
}) {
  const clamp = (v: number) => Math.max(min, Math.min(max, v));
  return (
    <div className="num-stepper">
      <button type="button" className="ns-btn" disabled={value <= min} onClick={() => onChange(clamp(value - step))}>
        −
      </button>
      <div className="ns-val">{render ? render(value) : value}</div>
      <button type="button" className="ns-btn" disabled={value >= max} onClick={() => onChange(clamp(value + step))}>
        ＋
      </button>
    </div>
  );
}

export default function Setup({
  onCreated,
  onBack,
}: {
  onCreated: (t: Trip) => void;
  onBack?: () => void;
}) {
  const [city, setCity] = useState("shanghai");
  const [days, setDays] = useState(2);
  const [budget, setBudget] = useState(1500);
  const [people, setPeople] = useState(3);
  const [start, setStart] = useState(defaultStart);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const cityMeta = { emoji: CITY_META[city]?.emoji ?? "📍", name: CITY_META[city]?.name ?? city };

  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const t = await api.createTrip({
        city,
        days,
        total_budget: budget,
        initial_people: people,
        start_at: `${start.date}T${start.time}`,
      });
      onCreated(t);
    } catch (e) {
      setErr("无法创建行程:" + (e instanceof Error ? e.message : String(e)) + "。请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page setup">
      {onBack && (
        <button className="btn btn-ghost btn-sm" style={{ marginBottom: 8 }} onClick={onBack}>
          ← 返回
        </button>
      )}
      <section className="hero">
        <span className="hero-emoji">🧳</span>
        <h1>
          {people} 个人,{people} 种想要,一次出发
        </h1>
        <p>
          有人想逛展,有人只认美食,有人不想走远。
          <br />
          别再一个人拍板、其他人默默妥协了 ——
          <br />
          让 AI 把每个人的<b>必去</b>放进行程,把<b>取舍解释清楚</b>,把<b>谁让步了记下来</b>。
        </p>
      </section>

      <div className="card form-card">
        <label className="field-label">想去哪座城市?</label>
        <CityPicker value={city} onChange={setCity} />

        <label className="field-label">玩几天?</label>
        <NumStepper
          value={days}
          onChange={setDays}
          min={DAYS_MIN}
          max={DAYS_MAX}
          render={(v) => `${v} 天`}
        />
        <p className="muted small">
          可选 {DAYS_MIN}–{DAYS_MAX} 天。
        </p>

        <label className="field-label">总预算(元)</label>
        <NumStepper
          value={budget}
          onChange={setBudget}
          min={BUDGET_MIN}
          max={BUDGET_MAX}
          step={100}
          render={(v) => `¥${v}`}
        />

        <label className="field-label">一起去几个人?</label>
        <NumStepper value={people} onChange={setPeople} min={PEOPLE_MIN} max={PEOPLE_MAX} render={(v) => `${v} 人`} />
        <p className="muted small">创建后「偏好」页会按这个人数预置好待填写的成员位(可自由增减)。</p>

        <label className="field-label">什么时候出发?</label>
        <div className="stepper date-time">
          <input
            type="date"
            value={start.date}
            onChange={(e) => setStart((s) => ({ ...s, date: e.target.value }))}
          />
          <input
            type="time"
            value={start.time}
            onChange={(e) => setStart((s) => ({ ...s, time: e.target.value }))}
          />
        </div>
        <p className="muted small">
          出发时刻已过 = 行程「已开始」,系统会随墙钟自动冻结已过期的天数;
          未来的出发时间则保持「未开始」。之后可在「规则」页随时触达。
        </p>

        {err && <div className="error-banner">⚠️ {err}</div>}
        <button className="btn btn-primary btn-lg" disabled={busy} onClick={create}>
          {busy ? "准备中…" : "开始 >> "}
          {cityMeta.emoji} {cityMeta.name}之旅
        </button>
      </div>
    </div>
  );
}

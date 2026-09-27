import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { CITY_META, DayPlan, DayWeather, Explanation, fmtMinute, Trip } from "../types";
import { dayDateLabel, fmtStartAt, tripTimeState } from "../time";

export default function PlanView({ trip }: { trip: Trip; refresh: () => Promise<void> }) {
  const plan = trip.current_plan;
  const timeState = tripTimeState(trip);
  const [weather, setWeather] = useState<DayWeather[]>([]);
  const byPoi = useMemo(() => {
    const m = new Map<string, Explanation>();
    plan?.explanations.forEach((e) => m.set(e.poi_id, e));
    return m;
  }, [plan]);

  // 逐日真实天气(AI 排程时也已参考它);取不到就为空,不显示
  useEffect(() => {
    if (!trip.start_at) {
      setWeather([]);
      return;
    }
    let alive = true;
    api
      .getWeather(trip.id)
      .then((d) => {
        if (alive) setWeather(d.days);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [trip.id, trip.start_at]);

  if (!plan) {
    return (
      <div className="page empty-state">
        <div className="big-emoji">🗺️</div>
        <p>还没有行程,先去「偏好」生成一份吧</p>
      </div>
    );
  }

  const days = [...plan.days].sort((a, b) => a.day - b.day);
  const budgetPct = Math.min(100, (plan.total_spent / plan.total_budget) * 100);

  return (
    <div className="page">
      <div className="page-head">
        <h2>
          {CITY_META[plan.city]?.emoji ?? ""} {plan.trip_name}{" "}
          {plan.engine && (
            <span className={`engine-badge ${plan.engine.startsWith("ai") ? "ai" : "opt"}`}>
              🤖 AI 编排
            </span>
          )}
        </h2>
        <div className="budget-bar">
          <div className="budget-fill" style={{ width: `${budgetPct}%` }} />
        </div>
        <div className="budget-label">
          已花 <b>¥{plan.total_spent}</b> / ¥{plan.total_budget}
          <span className="muted"> · 全队 {trip.participants.length} 人 · 含食宿</span>
        </div>
        {plan.cost_breakdown && (
          <div className="muted small cost-breakdown">
            🎫 门票 ¥{plan.cost_breakdown.tickets}(每人×{trip.participants.length}) · 🚕 交通 ¥
            {plan.cost_breakdown.transport} · 🍜 餐饮 ¥{plan.cost_breakdown.food} · 🏨 住宿 ¥
            {plan.cost_breakdown.lodging}
          </div>
        )}
        {timeState.started ? (
          <div className="banner mode-banner">
            {timeState.current_day === 0
              ? "🟢 进行中 · 正在第 1 天"
              : `🧊 进行中 · 前 ${timeState.current_day} 天已冻结 · 今天是第 ${timeState.current_day + 1} 天`}
          </div>
        ) : (
          fmtStartAt(trip) && (
            <div className="banner mode-banner upcoming">
              ⏳ 未开始 · {fmtStartAt(trip)} 启程 · 想改需求随时回「偏好」/「规则」
            </div>
          )
        )}
      </div>

      {days.map((d) => (
        <DayCol
          key={d.day}
          d={d}
          byPoi={byPoi}
          dateLabel={dayDateLabel(trip, d.day)}
          weather={weather[d.day]}
          frozen={timeState.started && d.day < timeState.current_day}
          isToday={timeState.started && d.day === timeState.current_day}
        />
      ))}
    </div>
  );
}

function DayCol({
  d,
  byPoi,
  dateLabel,
  weather,
  frozen,
  isToday,
}: {
  d: DayPlan;
  byPoi: Map<string, Explanation>;
  dateLabel: string;
  weather?: DayWeather;
  frozen: boolean;
  isToday: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <section className={`day-col ${frozen ? "frozen" : ""} ${isToday ? "today" : ""}`}>
      <div className="day-label">
        <span className="day-badge">第 {d.day + 1} 天</span>
        {dateLabel && <span className="day-date">{dateLabel}</span>}
        {weather && (
          <span className="day-weather" title={`${weather.text}(AI 已参考)`}>
            {weather.icon}
            {weather.tmin != null && weather.tmax != null
              ? ` ${Math.round(weather.tmin)}~${Math.round(weather.tmax)}℃`
              : ` ${weather.text}`}
            {weather.precip != null && weather.precip >= 50 ? ` 💧${weather.precip}%` : ""}
          </span>
        )}
        {frozen && <span className="day-state frozen">🧊 已冻结</span>}
        {isToday && <span className="day-state today">今天</span>}
        <span className="day-spent">¥{d.day_spent}</span>
      </div>
      {d.stops.length === 0 ? (
        <div className="card day-empty">当日暂无安排 · {d.day_end_note}</div>
      ) : (
        <div className="timeline">
          {d.stops.map((s, i) => {
            const ex = byPoi.get(s.poi_id);
            const open = openId === s.poi_id;
            return (
              <div key={s.poi_id} className="tl-item">
                <div className="tl-rail">
                  <span className="tl-dot" />
                  {i < d.stops.length - 1 && <span className="tl-line" />}
                </div>
                <div className="card stop-card">
                  <div className="stop-row" onClick={() => setOpenId(open ? null : s.poi_id)}>
                    <span className="stop-emoji">{s.emoji}</span>
                    <div className="stop-main">
                      <div className="stop-name">{s.name}</div>
                      <div className="stop-meta">
                        {fmtMinute(s.start_min)}–{fmtMinute(s.end_min)} ·{" "}
                        {Number(((s.end_min - s.start_min) / 60).toFixed(1))}h
                        {s.travel_min > 0 && (
                          <span className={`travel ${s.travel_mode === "步行" ? "walk" : "taxi"}`}>
                            {s.travel_mode}{s.travel_min}′
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="stop-price">{s.price > 0 ? `¥${s.price}` : "免费"}</span>
                  </div>
                  {open && ex && (
                    <div className="explain">
                      <div className="explain-title">💡 {ex.title}</div>
                      <ul>
                        {ex.reasons.map((r, j) => (
                          <li key={j}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
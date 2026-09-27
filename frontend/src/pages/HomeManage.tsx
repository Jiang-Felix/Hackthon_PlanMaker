import { useEffect, useState } from "react";
import { api } from "../api/client";
import { fmtStartAt, tripStatus, TripStatus } from "../time";
import { CITY_META, Trip } from "../types";

const STATUS: Record<TripStatus, { label: string; cls: string; icon: string }> = {
  upcoming: { label: "未开始", cls: "upcoming", icon: "⏳" },
  ongoing: { label: "进行中", cls: "ongoing", icon: "🟢" },
  done: { label: "已完成", cls: "done", icon: "✅" },
};

export default function HomeManage({
  onOpenTrip,
  onShare,
}: {
  onOpenTrip: (t: Trip) => void;
  onShare: (t: Trip) => void;
}) {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = () =>
    api
      .getTrips()
      .then(setTrips)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const del = async (id: string) => {
    if (!window.confirm("删除这个行程?")) return;
    try {
      await api.deleteTrip(id);
    } catch {
      /* 删除失败不阻塞 */
    }
    load();
  };

  if (loading) {
    return (
      <div className="page home-page">
        <div className="muted">加载中…</div>
      </div>
    );
  }

  return (
    <div className="page home-page">
      <div className="page-head">
        <h2>🧳 我的行程</h2>
        <p className="muted">点卡片进入工作区继续安排;点底部「＋ 创建」开新行程。</p>
      </div>
      {err && <div className="error-banner">⚠️ {err}</div>}

      {trips.length === 0 ? (
        <div className="card empty-state">
          <div className="big-emoji">🧳</div>
          <p>还没有行程 —— 点底部中间的「＋创建」,马上出发</p>
        </div>
      ) : (
        trips.map((t) => {
          const st = STATUS[tripStatus(t)];
          const plan = t.current_plan;
          const pct = plan ? Math.min(100, (plan.total_spent / plan.total_budget) * 100) : 0;
          return (
            <div key={t.id} className="card trip-card" onClick={() => onOpenTrip(t)}>
              <div className="trip-card-head">
                <span className="city-emoji">{CITY_META[t.city]?.emoji ?? "📍"}</span>
                <b>{CITY_META[t.city]?.name ?? t.city} · {t.days}天</b>
                <span className={`trip-badge ${st.cls}`}>{st.icon} {st.label}</span>
              </div>
              <div className="trip-card-meta">
                {fmtStartAt(t) && <span>🗓 {fmtStartAt(t)} 出发</span>}
                {plan ? (
                  <span>
                    💰 ¥{plan.total_spent.toFixed(0)} / {plan.total_budget.toFixed(0)}
                  </span>
                ) : (
                  <span className="muted">还没生成行程 · {t.participants.length} 位成员</span>
                )}
              </div>
              {plan && (
                <div className="mini-progress">
                  <div className="mini-progress-fill" style={{ width: `${pct}%` }} />
                </div>
              )}
              <div className="trip-card-actions">
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={!plan}
                  title={plan ? "把这次行程分享到社区" : "先生成行程再分享"}
                  onClick={(e) => {
                    e.stopPropagation();
                    onShare(t);
                  }}
                >
                  📤 分享
                </button>
                <button
                  className="btn btn-ghost btn-sm trip-del"
                  onClick={(e) => {
                    e.stopPropagation();
                    del(t.id);
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
import { ReplanResult, Plan, fmtMinute } from "../types";

/**
 * 「更新行程」的结果面板 —— 从原动态调整页(ReplanView)抽出,供「规则」页在
 * 已开始状态下使用。展示换入/换出 diff + 受影响成员 + 新路线。
 * `oldPlan` 用于给「换出」的景点查名字(它只存在于旧计划);新名字取自 result.plan。
 */
export default function ReplanDiff({ result, oldPlan }: { result: ReplanResult; oldPlan: Plan | null }) {
  const poiNames = new Map<string, string>();
  for (const e of result.plan?.explanations ?? []) {
    poiNames.set(e.poi_id, e.title.replace(/^为什么不?安排 /, ""));
  }
  for (const e of oldPlan?.explanations ?? []) {
    if (!poiNames.has(e.poi_id)) poiNames.set(e.poi_id, e.title.replace(/^为什么不?安排 /, ""));
  }

  return (
    <div className="diff-box">
      <h3>本次调整</h3>
      {result.added.length > 0 && (
        <div className="diff-row">
          <span className="diff-label add">换入</span>
          {result.added.map((pid) => (
            <span key={pid} className="diff-chip add">＋ {poiNames.get(pid) ?? pid}</span>
          ))}
        </div>
      )}
      {result.removed.length > 0 && (
        <div className="diff-row">
          <span className="diff-label rm">换出</span>
          {result.removed.map((pid) => (
            <span key={pid} className="diff-chip rm">－ {poiNames.get(pid) ?? pid}</span>
          ))}
        </div>
      )}
      {result.added.length === 0 && result.removed.length === 0 && (
        <p className="muted">剩余路线没有变化的余地,去看「公平」页谁又让了步。</p>
      )}

      <div className="new-days">
        {result.plan.days.map((d) => (
          <div key={d.day} className="mini-day">
            <span className="day-badge">第 {d.day + 1} 天</span>
            <div>
              {d.stops.map((s) => (
                <div key={s.poi_id} className="mini-stop">
                  {s.emoji} {s.name}{" "}
                  <span className="muted">
                    {fmtMinute(s.start_min)}–{fmtMinute(s.end_min)}
                  </span>
                </div>
              ))}
              {d.stops.length === 0 && <span className="muted">(空)</span>}
            </div>
          </div>
        ))}
      </div>
      <p className="muted small">受影响成员:{result.affected.length} 人 · 去「公平」页查看最新账本</p>
    </div>
  );
}
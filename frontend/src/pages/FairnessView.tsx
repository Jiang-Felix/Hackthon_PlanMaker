import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ConcessionKind, LEVEL_META, POI, PreferenceVocab, Trip } from "../types";

const prefLevels: ("must" | "want" | "ok")[] = ["must", "want", "ok"];

/**
 * 缺口 → 颜色。**用整数 `deficit` 而不是比率阈值**:2 天行程只有几个名额,
 * 一个名额就摆动 33–50%,比率在阈值上纯是噪声。
 */
function deficitLevel(deficit: number): "good" | "mid" | "bad" {
  return deficit <= 0 ? "good" : deficit === 1 ? "mid" : "bad";
}

/** 软偏好标签的四种结局 —— 图标与配色集中一处,避免三元表达式越堆越深。 */
const SOFT_CHIP = {
  done: { cls: "done", icon: "✓" },
  miss: { cls: "miss", icon: "✗" },
  violated: { cls: "violated", icon: "⚠️" },
  // 模型整个漏答的标签:中性灰的「?」—— 是"没评估",不是"没做到"
  unaccounted: { cls: "na", icon: "?" },
} as const;

/** 让步账本行的措辞 —— 按**真实原因**区分,不再一律说"让出了"。 */
const KIND_META: Record<ConcessionKind, { icon: string; verb: string }> = {
  passed_over: { icon: "🔄", verb: "让出了" },
  out_of_capacity: { icon: "📦", verb: "没能排进" },
  refused_by_other: { icon: "🚫", verb: "因他人拒绝而未排" },
};

export default function FairnessView({ trip }: { trip: Trip }) {
  const plan = trip.current_plan;
  const fair = plan?.fairness;
  const [poiMap, setPoiMap] = useState<Record<string, POI>>({});
  const [vocab, setVocab] = useState<PreferenceVocab | null>(null);

  useEffect(() => {
    api.getPois(trip.city).then((ps) => {
      setPoiMap(Object.fromEntries(ps.map((p) => [p.id, p])));
    });
    api.getVocab().then(setVocab).catch(() => setVocab(null));
  }, [trip.city]);

  // 软偏好标签 id → 中文名 + 所属类别的 emoji(后端只回 id,名字在前端查表)
  const tagMap = useMemo(() => {
    const m: Record<string, { label: string; emoji: string }> = {};
    for (const cat of vocab?.categories ?? []) {
      for (const t of cat.tags) m[t.id] = { label: t.label, emoji: cat.emoji };
    }
    return m;
  }, [vocab]);

  const rows = fair?.participants ?? [];
  // ⚠️ 必须先滤掉 `share == null`(未提意愿的人)。`Math.min` 会把 null 当 0,
  // 于是「没人被牺牲」被误判成「有人 0 分」,整页报红。
  const scored = useMemo(
    () => rows.filter((r) => r.share !== null),
    [rows]
  );
  const anyoneOwed = rows.some((r) => r.deficit > 0);

  if (!fair) {
    return (
      <div className="page empty-state">
        <div className="big-emoji">⚖️</div>
        <p>先生成行程,再看谁被牺牲了、被牺牲了多少</p>
      </div>
    );
  }

  const pidLabel = (pid: string) => poiMap[pid]?.name ?? pid;
  const pidEmoji = (pid: string) => poiMap[pid]?.emoji ?? "📍";

  const softChip = (tag: string, kind: keyof typeof SOFT_CHIP) => {
    const meta = tagMap[tag];
    const { cls, icon } = SOFT_CHIP[kind];
    return (
      <span key={`${kind}-${tag}`} className={`poi-tag ${cls}`}>
        {icon} {meta?.emoji ?? "🏷️"} {meta?.label ?? tag}
      </span>
    );
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>⚖️ 公平账本</h2>
        <p className="muted">
          平衡不等于让每个人都满意,而是<b>每个人的高优先级诉求要有交代</b>、
          <b>没人被一直牺牲</b>。这里记的是「谁被亏欠了、亏欠了多少」,不是满意度百分比。
        </p>
      </div>

      {fair.contested_slots > 0 && (
        <p className="muted small">
          本次共 <b>{fair.contested_slots}</b> 个有人想要的停留,
          <b>{scored.length}</b> 人各应得约 <b>{fair.quota.toFixed(1)}</b> 个
          {fair.undeclared_slots > 0 && <>;另有 {fair.undeclared_slots} 个安排不在任何人的意愿清单内</>}。
        </p>
      )}

      {fair.summary_messages.map((m, i) => (
        <div key={i} className={`summary-msg ${anyoneOwed ? "warn" : ""}`}>
          {m}
        </div>
      ))}

      {rows.map((row) => {
        // N/A 分支:没提意愿 ≠ 极度不满。走中性渲染,绝不落成红色 0%。
        const na = row.share === null;
        const lv = deficitLevel(row.deficit);
        const pct = na ? 0 : Math.round((row.share as number) * 100);
        const softDeclared = row.soft_declared;
        const softAssessed = row.soft_cared > 0;
        return (
          <div key={row.participant_id} className="card fair-row">
            <div className="fair-head">
              <span className="avatar">{row.name.slice(0, 1)}</span>
              <b>{row.name}</b>
              <span className={`sat-big ${na ? "na" : lv}`}>
                {na ? "未提意愿" : row.deficit > 0 ? `欠 ${row.deficit} 个名额` : "足额"}
              </span>
              {row.concession_count > 0 && (
                <span className="concede-badge">让了 {row.concession_count} 次</span>
              )}
            </div>
            <div className={`sat-bar ${na ? "na" : ""}`}>
              <div className={`sat-fill ${na ? "na" : lv}`} style={{ width: `${pct}%` }} />
            </div>

            <div className="fair-metrics">
              <span className={`metric ${row.must_met === row.must_total ? "ok" : "warn"}`}>
                {row.must_met === row.must_total ? "✅" : "⚠️"} 必去 {row.must_met}/{row.must_total}
              </span>
              <span className="metric muted">
                意愿命中 {row.slots_got} / 你声明的 {row.wants_declared} 项
              </span>
              <span className={`metric ${lv}`}>
                {na ? "—" : `拿到 ${row.slots_got} / 应得 ${(row.slots_owed ?? 0).toFixed(1)}`}
              </span>
            </div>

            {softDeclared > 0 && (
              <div className="fair-level">
                <span className="tier-dot soft">软偏好</span>
                {softAssessed ? (
                  <>
                    <span className="metric muted">
                      {row.soft_cared}/{softDeclared}
                      {row.soft_rate !== null && ` · ${Math.round(row.soft_rate * 100)}%`}
                    </span>
                    {row.soft_satisfied.map((t) => softChip(t, "done"))}
                    {row.soft_missed.map((t) => softChip(t, "miss"))}
                    {row.soft_violated.map((t) => softChip(t, "violated"))}
                  </>
                ) : (
                  // 完全没拿到裁决 ≠ 一项都没做到。中性灰,绝不落成 0%。
                  <span className="poi-tag na">未评估</span>
                )}
                {/* 部分漏答:模型整个漏掉的标签必须逐个显示 —— 否则"声明了不吃辣"
                    在页面上就是什么都不显示。 */}
                {row.soft_unaccounted.map((t) => softChip(t, "unaccounted"))}
              </div>
            )}

            <div className="fair-detail">
              {prefLevels.map((level) => {
                const met = row.satisfied[level] ?? [];
                const miss = row.missing[level] ?? [];
                if (met.length === 0 && miss.length === 0) return null;
                return (
                  <div key={level} className="fair-level">
                    <span className={`tier-dot ${level}`}>{LEVEL_META[level].label}</span>
                    {met.map((pid) => (
                      <span key={pid} className="poi-tag done">✓ {pidEmoji(pid)} {pidLabel(pid)}</span>
                    ))}
                    {miss.map((pid) => (
                      <span key={pid} className="poi-tag miss">✗ {pidEmoji(pid)} {pidLabel(pid)}</span>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {fair.concessions.length > 0 && (
        <section className="card ledger-card">
          <h3>🔄 让步时间线</h3>
          <div className="ledger">
            {fair.concessions.map((c) => {
              const meta = KIND_META[c.kind] ?? KIND_META.passed_over;
              return (
                <div key={`${c.round}-${c.participant_id}-${c.loser_poi}`} className="ledger-row">
                  <span className="round-chip">#{c.round}</span>
                  <div>
                    <b>{c.participant_name}</b> {meta.verb} <b>{meta.icon} {c.loser_poi}</b>
                    <div className="muted small">{c.reason}</div>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="muted small">
            只有「本可安排却未被采纳」才记账。下次排程时,<b>欠得越多的人越优先照顾</b>
            (轮换优先权)—— 补偿到位后欠账归零,优先权自动消失。
          </p>
        </section>
      )}
    </div>
  );
}

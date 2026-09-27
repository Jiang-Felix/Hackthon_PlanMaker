import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import RankBoard from "../components/RankBoard";
import SoftPrefPanel from "../components/SoftPrefPanel";
import { tripTimeState } from "../time";
import {
  LEVEL_META,
  Participant,
  POI,
  PreferenceVocab,
  PrefLevel,
  RankItem,
  StructuredPref,
  TagPref,
  Trip,
} from "../types";

interface Props {
  trip: Trip;
  onUpdated: () => Promise<void>;
  /** 偏好填完后进入「规则」页(生成行程的按钮在那一页) */
  onGoRules: () => void;
}

export default function Preferences({ trip, onUpdated, onGoRules }: Props) {
  const [pois, setPois] = useState<POI[]>([]);
  const [vocab, setVocab] = useState<PreferenceVocab | null>(null);
  const [drafts, setDrafts] = useState<{ key: number; name: string; text: string }[]>([]);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 分步解析可视化:stage 表示当前进行到哪一步,preview 逐步填入结果
  const [stage, setStage] = useState<null | "poi" | "soft">(null);
  const [preview, setPreview] = useState<{ structured: StructuredPref; soft: TagPref | null } | null>(null);
  const addBtnRef = useRef<HTMLButtonElement | null>(null);
  const [flashAdd, setFlashAdd] = useState(false);
  /** 每个行程只按「初始人数」预置一次成员位 */
  const seededRef = useRef<string | null>(null);

  useEffect(() => {
    api.getPois(trip.city).then(setPois).catch(() => {});
    api.getVocab().then(setVocab).catch(() => {});
  }, [trip.city]);

  // 创建时设定的初始人数 → 预置同等数量的待填写成员位(只是本地草稿;
  // 未填写的不会被记为成员,「至少一位成员」的校验与成员卡片的渲染都不受影响)
  useEffect(() => {
    if (seededRef.current === trip.id) return;
    seededRef.current = trip.id;
    const n = trip.initial_people ?? 0;
    if (n > 0 && trip.participants.length === 0) {
      const base = Date.now();
      setDrafts(Array.from({ length: n }, (_, i) => ({ key: base + i, name: "", text: "" })));
    }
    // 依赖故意只取 trip.id:只在切换行程时判定一次,人数/成员数的后续变化不该重新铺满草稿
  }, [trip.id]);

  const addDraft = () => {
    setDrafts((d) => [...d, { key: Date.now(), name: "", text: "" }]);
    setErr(null);
  };

  /** 两步 AI 理解,分步可视化:① 景点意愿 → ② 偏好态度 → 落库 */
  const reparse = async (name: string, text: string) => {
    if (!text.trim()) return;
    setBusyName(name);
    setErr(null);
    setPreview(null);
    try {
      setStage("poi");
      const structured = await api.parsePoi(trip.city, text);
      setPreview({ structured, soft: null });

      setStage("soft");
      const soft = await api.parseSoft(text);
      setPreview({ structured, soft });
      setStage(null);
      // 短暂停留,让用户看清「② 解读偏好态度」的结果再落库(纯视觉,不参与逻辑)
      await new Promise((r) => setTimeout(r, 700));

      await api.addParticipant(trip.id, {
        name,
        natural_text: text,
        structured,
        soft,
        already_parsed: true, // 本页已用 /api/parse/* 解析过,后端只记录原文、不再调 AI
      });
      await onUpdated();
      setDrafts((d) => d.filter((x) => x.name !== name));
      setHint(null);
    } catch (e) {
      setErr(
        "AI 理解失败:" + (e instanceof Error ? e.message : String(e)) +
          "。请稍后重试,或确认网络与 AI 服务正常。",
      );
    } finally {
      setBusyName(null);
      setStage(null);
      setPreview(null);
    }
  };

  const onGenerate = () => {
    if (trip.participants.length === 0) {
      setHint("👆 先添加至少一位成员并完成 AI 解析,才能继续设置规则");
      setFlashAdd(true);
      setTimeout(() => setFlashAdd(false), 1600);
      addBtnRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    onGoRules();
  };

  const timeState = tripTimeState(trip);

  return (
    <div className="page">
      <div className="page-head">
        <h2>谁一起去?先说好“各自的底线”</h2>
        <p className="muted">
          每人用一句话告诉 AI 你想去哪儿、不想去哪儿,系统按
          <b> 必去 &gt; 想去 &gt; 可接受 &gt; 不去 </b>分配行程优先级。
        </p>
        <button
          ref={addBtnRef}
          className={`btn btn-ghost ${flashAdd ? "pulse" : ""}`}
          onClick={addDraft}
        >
          ＋ 添加一位同行成员
        </button>
      </div>

      {err && <div className="error-banner">⚠️ {err}</div>}

      {timeState.started && (
        <div className="banner mode-banner">
          {timeState.current_day === 0
            ? "🟢 行程已开始,正在第 1 天"
            : `🧊 行程已开始 · 前 ${timeState.current_day} 天已冻结 · 今天是第 ${timeState.current_day + 1} 天`}
          <div className="muted small">
            改完大家的需求,去「规则」页点<b>「更新行程」</b>—— 已冻结的天原样保留,只重排剩余天。
          </div>
        </div>
      )}

      {trip.participants.map((p) => (
        <MemberCard key={p.id} p={p} pois={pois} vocab={vocab} tripId={trip.id} onUpdated={onUpdated} />
      ))}

      {drafts.map((d) => {
        const ready = d.name.trim() && d.text.trim() && busyName !== d.name;
        return (
          <div key={d.key} className="card member-card draft">
            <div className="member-title">
              <input
                className="field-inline"
                placeholder="TA 的名字"
                value={d.name}
                onChange={(e) =>
                  setDrafts((list) =>
                    list.map((x) => (x.key === d.key ? { ...x, name: e.target.value } : x))
                  )
                }
              />
              <button
                className="draft-del"
                title="移除这一位"
                onClick={() => setDrafts((list) => list.filter((x) => x.key !== d.key))}
              >
                ✕
              </button>
            </div>
            <textarea
              className="nl-input"
              rows={3}
              placeholder="例:我超想去上海天文馆,喜欢美食和逛展,不喜欢去乐园"
              value={d.text}
              onChange={(e) =>
                setDrafts((list) =>
                  list.map((x) => (x.key === d.key ? { ...x, text: e.target.value } : x))
                )
              }
            />
            <button
              className="btn btn-primary"
              disabled={!ready}
              onClick={() => reparse(d.name.trim(), d.text)}
            >
              ✨ AI 听懂我的心
            </button>

            {/* 两步 AI 理解的可视化:逐步显示进度与结果 */}
            {busyName === d.name && (
              <div className="ai-steps">
                <StepRow
                  index="①"
                  title="解析景点意愿"
                  state={stage === "poi" ? "running" : preview ? "done" : "waiting"}
                />
                {preview?.structured && (
                  <ChipPreview
                    pref={preview.structured}
                    labelOf={(id) => pois.find((p) => p.id === id)?.name ?? id}
                  />
                )}
                <StepRow
                  index="②"
                  title="解读偏好态度"
                  state={stage === "soft" ? "running" : preview?.soft ? "done" : "waiting"}
                />
                {preview?.soft && <ChipPreview pref={preview.soft} labelOf={(id) => tagLabel(vocab, id)} />}
              </div>
            )}

            {!ready && (
              <p className="btn-hint">
                {!d.name.trim()
                  ? "先填上 TA 的名字"
                  : !d.text.trim()
                    ? "再写一句 TA 想/不想去哪儿"
                    : busyName === d.name
                      ? "解析中…"
                      : ""}
              </p>
            )}
          </div>
        );
      })}

      <div className="sticky-actions">
        {hint && <div className="hint-bar">{hint}</div>}
        <button className="btn btn-primary btn-lg" onClick={onGenerate}>
          设置全局规则 →
          <span className="gen-count">{trip.participants.length > 0 ? `${trip.participants.length} 位成员` : ""}</span>
        </button>
      </div>
    </div>
  );
}

function MemberCard({
  p,
  pois,
  vocab,
  tripId,
  onUpdated,
}: {
  p: Participant;
  pois: POI[];
  vocab: PreferenceVocab | null;
  tripId: string;
  onUpdated: () => Promise<void>;
}) {
  const [retext, setRetext] = useState("");
  const [showRetext, setShowRetext] = useState(false);
  const [showPick, setShowPick] = useState(false);
  const [showSoft, setShowSoft] = useState(false);
  const [busy, setBusy] = useState(false);

  const poisById = useMemo(() => Object.fromEntries(pois.map((x) => [x.id, x])), [pois]);

  const applyPref = useCallback(
    async (pref: StructuredPref) => {
      setBusy(true);
      try {
        await api.addParticipant(tripId, { name: p.name, structured: pref });
        await onUpdated();
      } finally {
        setBusy(false);
      }
    },
    [tripId, p.name, onUpdated]
  );

  const applySoft = useCallback(
    async (soft: TagPref) => {
      setBusy(true);
      try {
        await api.addParticipant(tripId, { name: p.name, soft });
        await onUpdated();
      } finally {
        setBusy(false);
      }
    },
    [tripId, p.name, onUpdated]
  );

  /** POI → 榜单项(泛化后的 RankBoard 需要统一的 RankItem) */
  const poiItems: RankItem[] = useMemo(
    () =>
      pois.map((x) => ({
        id: x.id,
        name: x.name,
        emoji: x.emoji,
        meta: `${x.price > 0 ? `¥${x.price}` : "免费"} · ${x.hours}h`,
        tags: x.tags,
        aliases: x.aliases,
        desc: x.desc,
      })),
    [pois],
  );

  const softCount = (Object.values(p.soft ?? {}) as string[][]).reduce((n, a) => n + (a?.length ?? 0), 0);

  const toggle = (lv: PrefLevel, pid: string) => {
    const list = p.pref[lv];
    const pref: StructuredPref = structuredClone(p.pref);
    pref[lv] = list.includes(pid) ? list.filter((x) => x !== pid) : [...list, pid];
    applyPref(pref);
  };

  /** 软偏好标签的移除(chip 上的 ×):与 POI 的 toggle 一样,点一下即从该档去掉 */
  const removeSoft = (lv: PrefLevel, tag: string) => {
    const soft: TagPref = structuredClone(p.soft ?? { refuse: [], must: [], want: [], ok: [] });
    soft[lv] = (soft[lv] ?? []).filter((x) => x !== tag);
    applySoft(soft);
  };

  return (
    <div className="card member-card">
      <div className="member-title">
        <span className="avatar">{p.name.slice(0, 1)}</span>
        <b>{p.name}</b>
      </div>

      {/* 输入历史:原始输入 + 每次补充 */}
      {inputHistory(p).length > 0 && (
        <div className="nl-history">
          {inputHistory(p).map((t, i) => (
            <div key={i} className="nl-line">
              <span className={`nl-tag ${i === 0 ? "origin" : "extra"}`}>
                {i === 0 ? "原始" : "补充"}
              </span>
              <span className="nl-line-text">{t}</span>
            </div>
          ))}
        </div>
      )}

      {(Object.keys(LEVEL_META) as PrefLevel[]).map((lv) => (
        <div key={lv} className="chip-row">
          <span className={`tier-dot ${lv}`}>{LEVEL_META[lv].label}</span>
          <div className="chips">
            {p.pref[lv].map((pid) => (
              <button
                key={pid}
                className={`chip ${lv}`}
                title={poisById[pid]?.desc}
                onClick={() => toggle(lv, pid)}
              >
                {poisById[pid]?.emoji ?? "📍"} {poisById[pid]?.name ?? pid}
                <span className="chip-x">×</span>
              </button>
            ))}
            {p.pref[lv].length === 0 && <span className="chip-empty">—</span>}
          </div>
        </div>
      ))}

      {/* 偏好意愿:与地点意愿**同款**四档可视化(避免/一定要/倾向/可以),点 × 即移除 */}
      <div className="pref-sect-label">偏好意愿</div>
      {softCount === 0 ? (
        <div className="chip-row">
          <span className="chip-empty">还没表达偏好意愿 —— 点下方「调整偏好排行」</span>
        </div>
      ) : (
        (Object.keys(SOFT_LEVEL_META) as PrefLevel[]).map((lv) => {
          const tags = (p.soft?.[lv] ?? []) as string[];
          return (
            <div key={`soft-${lv}`} className="chip-row">
              <span className={`tier-dot ${lv}`}>{SOFT_LEVEL_META[lv]}</span>
              <div className="chips">
                {tags.map((t) => {
                  const meta = softTagMeta(vocab, t);
                  return (
                    <button key={t} className={`chip ${lv}`} onClick={() => removeSoft(lv, t)}>
                      {meta.emoji} {meta.label}
                      <span className="chip-x">×</span>
                    </button>
                  );
                })}
                {tags.length === 0 && <span className="chip-empty">—</span>}
              </div>
            </div>
          );
        })
      )}

      <div className="member-tools">
        <button className="btn btn-ghost btn-sm" onClick={() => setShowPick((s) => !s)}>
          🏷️ 调整地点排行
        </button>
        <button
          className={`btn btn-ghost btn-sm ${showSoft ? "active-tool" : ""}`}
          onClick={() => setShowSoft((s) => !s)}
        >
          🎛️ 调整偏好排行{softCount > 0 ? ` (${softCount})` : ""}
        </button>
        <button
          className={`btn btn-ghost btn-sm ${showRetext ? "active-tool" : ""}`}
          onClick={() => {
            setShowRetext((s) => !s);
            setRetext("");
          }}
        >
          📝 再补充几句
        </button>
        {busy && <span className="muted">保存中…</span>}
      </div>

      {showRetext && (
        <div className="retext">
          <textarea
            className="nl-input"
            rows={2}
            placeholder="补充几句:比如「还想看天文馆」「怕累不想走太多」——会在原有基础上合并,不会重排"
            value={retext}
            onChange={(e) => setRetext(e.target.value)}
          />
          <button
            className="btn btn-primary btn-sm"
            disabled={busy || !retext.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                await api.addParticipant(tripId, { name: p.name, natural_text: retext, merge: true });
                await onUpdated();
                setRetext("");
                setShowRetext(false);
              } finally {
                setBusy(false);
              }
            }}
          >
            并入我的意愿
          </button>
        </div>
      )}

      {showSoft && (
        <div className="soft-wrap">
          <p className="muted small">
            除景点外的模糊偏好(体力/天气/作息/消费…),会作为有效条件交给 AI 排程。
          </p>
          <SoftPrefPanel soft={p.soft} vocab={vocab} onChange={applySoft} busy={busy} />
        </div>
      )}

      {showPick && (
        <RankBoard
          items={poiItems}
          pref={p.pref}
          busy={busy}
          onChange={(next) => applyPref(next)}
          boardFirst
          showLabel={false}
        />
      )}
    </div>
  );
}
/* ---------- 分步 AI 理解的可视化小组件 ---------- */

/** 输入历史:优先用 natural_inputs;老数据/兼容回退到 natural_text */
function inputHistory(p: Participant): string[] {
  if (p.natural_inputs?.length) return p.natural_inputs;
  return p.natural_text ? [p.natural_text] : [];
}

function tagLabel(vocab: PreferenceVocab | null, id: string): string {
  for (const c of vocab?.categories ?? []) {
    const t = c.tags.find((x) => x.id === id);
    if (t) return t.label;
  }
  return id;
}

const LEVEL_SHORT: Record<PrefLevel, string> = { must: "必", want: "想", ok: "可", refuse: "拒" };

/** 偏好意愿(软偏好)的四档显示名 —— 与地点意愿同款可视化,顺序也一致(refuse 打头) */
const SOFT_LEVEL_META: Record<PrefLevel, string> = {
  refuse: "避免",
  must: "一定要",
  want: "倾向",
  ok: "可以",
};

/** 软偏好标签 id → 中文名 + 所属类别的 emoji(成员卡片上一眼可读) */
function softTagMeta(vocab: PreferenceVocab | null, id: string): { label: string; emoji: string } {
  for (const c of vocab?.categories ?? []) {
    const t = c.tags.find((x) => x.id === id);
    if (t) return { label: t.label, emoji: c.emoji };
  }
  return { label: id, emoji: "🏷️" };
}

function StepRow({
  index,
  title,
  state,
}: {
  index: string;
  title: string;
  state: "waiting" | "running" | "done";
}) {
  return (
    <div className={`ai-step ${state}`}>
      <span className="ai-step-icon">
        {state === "running" ? <span className="spinner-sm" /> : state === "done" ? "✓" : "○"}
      </span>
      <span className="ai-step-index">{index}</span>
      <span className="ai-step-title">{title}</span>
      {state === "running" && <span className="ai-step-note">AI 正在理解…</span>}
    </div>
  );
}

function ChipPreview({
  pref,
  labelOf,
}: {
  pref: StructuredPref;
  labelOf: (id: string) => string;
}) {
  const rows = (["must", "want", "ok", "refuse"] as PrefLevel[]).filter((lv) => pref[lv]?.length);
  if (!rows.length) return <div className="ai-step-empty">未识别出相关内容</div>;
  return (
    <div className="ai-preview">
      {rows.map((lv) => (
        <div key={lv} className="chips">
          <span className={`tier-dot ${lv}`}>{LEVEL_SHORT[lv]}</span>
          {pref[lv].map((id) => (
            <span key={id} className={`chip ${lv}`}>
              {labelOf(id)}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

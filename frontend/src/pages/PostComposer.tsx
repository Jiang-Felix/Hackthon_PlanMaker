import { useMemo, useState } from "react";
import { api } from "../api/client";
import { fileToDataUrl, isImageFile } from "../image";
import { dayDateLabel } from "../time";
import { CITY_META, fmtMinute, PostSection, Trip } from "../types";

const MAX_PHOTOS_PER_SECTION = 4;

/** 草稿段落:额外带一个前端 key 供 React 列表使用(提交时剔除)。 */
type DraftSection = PostSection & { key: string };

interface StopOption {
  poi_id: string;
  name: string;
  emoji: string;
  start_min: number;
  end_min: number;
}

interface DayOption {
  day: number;
  label: string;
  date: string;
}

const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));

/**
 * 行程分享的「发帖编辑界面」:通常发帖能力(正文 / 挂景点卡)+ 按地点或按天组织的图文段落。
 * 照片在前端压缩成 data URL 内嵌进帖子,不做文件上传。
 */
export default function PostComposer({
  trip,
  onDone,
  onBack,
}: {
  trip: Trip;
  onDone: () => void;
  onBack: () => void;
}) {
  const [text, setText] = useState("");
  const [poiIds, setPoiIds] = useState<string[]>([]);
  const [sections, setSections] = useState<DraftSection[]>([]);
  const [mode, setMode] = useState<"poi" | "day">("poi");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const city = trip.city;
  const plan = trip.current_plan;

  /** 行程计划里出现过的 POI(去重,保留首次出现的时间),作为「按地点」的候选。 */
  const stopOptions = useMemo<StopOption[]>(() => {
    const seen = new Set<string>();
    const out: StopOption[] = [];
    plan?.days.forEach((d) =>
      d.stops.forEach((s) => {
        if (seen.has(s.poi_id)) return;
        seen.add(s.poi_id);
        out.push({ poi_id: s.poi_id, name: s.name, emoji: s.emoji, start_min: s.start_min, end_min: s.end_min });
      }),
    );
    return out;
  }, [plan]);

  const dayOptions = useMemo<DayOption[]>(
    () =>
      (plan?.days ?? []).map((d) => ({
        day: d.day,
        label: `第 ${d.day + 1} 天`,
        date: dayDateLabel(trip, d.day),
      })),
    [plan, trip],
  );

  const addStop = (o: StopOption) => {
    if (sections.some((s) => s.kind === "poi" && s.poi_id === o.poi_id)) return; // 同一地点不重复加段
    setSections((prev) => [
      ...prev,
      {
        key: newKey(),
        kind: "poi",
        poi_id: o.poi_id,
        day: null,
        title: o.name,
        subtitle: `${fmtMinute(o.start_min)}–${fmtMinute(o.end_min)}`,
        note: "",
        photos: [],
      },
    ]);
  };

  const addDay = (o: DayOption) => {
    if (sections.some((s) => s.kind === "day" && s.day === o.day)) return;
    setSections((prev) => [
      ...prev,
      { key: newKey(), kind: "day", poi_id: "", day: o.day, title: o.label, subtitle: o.date, note: "", photos: [] },
    ]);
  };

  const patch = (key: string, p: Partial<DraftSection>) =>
    setSections((prev) => prev.map((s) => (s.key === key ? { ...s, ...p } : s)));

  const removeSection = (key: string) => setSections((prev) => prev.filter((s) => s.key !== key));

  const addPhotos = async (key: string, files: FileList | null) => {
    if (!files || files.length === 0) return;
    const room = MAX_PHOTOS_PER_SECTION - (sections.find((s) => s.key === key)?.photos.length ?? 0);
    if (room <= 0) {
      setErr(`每段最多 ${MAX_PHOTOS_PER_SECTION} 张照片`);
      return;
    }
    const picked = Array.from(files).filter(isImageFile).slice(0, room);
    if (picked.length === 0) {
      setErr("请选择图片文件");
      return;
    }
    setErr(files.length > room ? `每段最多 ${MAX_PHOTOS_PER_SECTION} 张,已只取前 ${room} 张` : "");
    setBusy(true);
    try {
      const urls = await Promise.all(picked.map((f) => fileToDataUrl(f)));
      setSections((prev) =>
        prev.map((s) =>
          s.key === key ? { ...s, photos: [...s.photos, ...urls.map((data) => ({ id: "", data, caption: "" }))] } : s,
        ),
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const removePhoto = (key: string, idx: number) =>
    setSections((prev) =>
      prev.map((s) => (s.key === key ? { ...s, photos: s.photos.filter((_, i) => i !== idx) } : s)),
    );

  const canSubmit = !busy && (text.trim().length > 0 || sections.length > 0);

  const submit = async () => {
    // 丢掉「既没写备注也没加照片」的空段落
    const kept = sections.filter((s) => s.note.trim() || s.photos.length > 0);
    if (!text.trim() && kept.length === 0) {
      setErr("写点什么,或给某个地点 / 某一天加一段图文");
      return;
    }
    // 段落里的地点也并进景点卡,免得帖子出现「📍一段但没有对应卡片」
    const ids = Array.from(new Set([...poiIds, ...kept.filter((s) => s.kind === "poi" && s.poi_id).map((s) => s.poi_id)]));
    setBusy(true);
    setErr("");
    try {
      await api.createPost({
        city,
        text: text.trim(),
        poi_ids: ids,
        trip_id: trip.id,
        sections: kept.map(({ key: _key, ...s }) => s),
      });
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page composer-page">
      <div className="page-head">
        <h2>📸 分享这次旅行</h2>
        <p className="muted">
          {CITY_META[city]?.emoji ?? "📍"} {CITY_META[city]?.name ?? city} · {trip.days} 天 —— 可以按地点或按天,
          给某一段配上照片和点评。
        </p>
      </div>

      <div className="card">
        <label className="field-label">正文</label>
        <textarea
          className="nl-input"
          rows={3}
          placeholder="这次旅行最想分享的一件事…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        {plan && (
          <>
            <label className="field-label">给某一处 / 某一天加一段图文</label>
            <div className="section-tabs">
              <button
                className={`tab-btn ${mode === "poi" ? "active" : ""}`}
                onClick={() => setMode("poi")}
              >
                📍 按地点
              </button>
              <button
                className={`tab-btn ${mode === "day" ? "active" : ""}`}
                onClick={() => setMode("day")}
              >
                📅 按天
              </button>
            </div>
            <div className="chips">
              {mode === "poi"
                ? stopOptions.map((o) => (
                    <button key={o.poi_id} className="chip" onClick={() => addStop(o)}>
                      {o.emoji} {o.name}
                    </button>
                  ))
                : dayOptions.map((o) => (
                    <button key={o.day} className="chip" onClick={() => addDay(o)}>
                      {o.label}
                      {o.date && ` · ${o.date}`}
                    </button>
                  ))}
            </div>
            <p className="muted small">点一个地点 / 一天,就在下面多出一段。</p>
          </>
        )}
      </div>

      {sections.map((s) => (
        <div key={s.key} className="card section-card">
          <div className="section-head">
            <span className="section-kind">{s.kind === "poi" ? "📍" : "📅"}</span>
            <b>{s.title}</b>
            {s.subtitle && <span className="muted small">{s.subtitle}</span>}
            <button className="chip-x" title="移除这一段" onClick={() => removeSection(s.key)}>
              ✕
            </button>
          </div>
          <textarea
            className="nl-input"
            rows={2}
            placeholder={s.kind === "poi" ? "在这个地点的感受…" : "这一天过得怎么样…"}
            value={s.note}
            onChange={(e) => patch(s.key, { note: e.target.value })}
          />
          <div className="photo-grid">
            {s.photos.map((ph, i) => (
              <div key={i} className="photo-wrap">
                <img className="photo-thumb" src={ph.data} alt={s.title} />
                <button className="photo-del" title="删除照片" onClick={() => removePhoto(s.key, i)}>
                  ✕
                </button>
              </div>
            ))}
            {s.photos.length < MAX_PHOTOS_PER_SECTION && (
              <label className="photo-add">
                ＋ 加照片
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => {
                    addPhotos(s.key, e.target.files);
                    e.currentTarget.value = "";
                  }}
                />
              </label>
            )}
          </div>
        </div>
      ))}

      {stopOptions.length > 0 && (
        <>
          <label className="field-label">挂几张景点卡(可选)</label>
          <div className="chips">
            {stopOptions.map((o) => {
              const on = poiIds.includes(o.poi_id);
              return (
                <button
                  key={o.poi_id}
                  className={`chip ${on ? "must" : ""}`}
                  onClick={() => setPoiIds(on ? poiIds.filter((x) => x !== o.poi_id) : [...poiIds, o.poi_id])}
                >
                  {o.emoji} {o.name}
                </button>
              );
            })}
          </div>
        </>
      )}

      {err && <div className="error-banner">⚠️ {err}</div>}

      <div className="composer-actions">
        <button className="btn btn-ghost" onClick={onBack}>
          取消
        </button>
        <button className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
          {busy ? "处理中…" : "发布"}
        </button>
      </div>
    </div>
  );
}

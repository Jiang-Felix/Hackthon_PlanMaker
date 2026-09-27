import { Fragment, useMemo, useState } from "react";
import { PrefLevel, RankItem } from "../types";

/**
 * 可搜索池 + 拖动到优先级榜(point-and-rank)—— 泛化版。
 *
 * 数据源抽象为 RankItem,因此同一套交互可服务:
 * - 景点意愿(POI:meta="¥30 · 4h",tags=POI 标签)
 * - 偏好意愿(词表标签:meta=类别名,category=类别 key)
 *
 * 交互(2026-09-27 按需求重做):
 * - 从搜索池**拖到榜单的任意位置**(松手前显示蓝色落点线)
 * - 榜单内**上下拖动换位**;或点 ✕ 移出、↑↓ 微调、点按升一格
 * - `boardFirst` 时榜单在搜索区**上方**(POI 意愿用);默认搜索区在上(软偏好用)
 * - `showLabel` 关闭「我的优先榜」标题块(POI 意愿用);软偏好仍用 label 显示类别名
 * - 所有写操作都做跨层去重(同一 id 只出现一次),经 onChange 上抛
 */
const ORDER: PrefLevel[] = ["must", "want", "ok", "refuse"];
const DEFAULT_TITLES: Record<PrefLevel, string> = {
  must: "🏆 必去榜",
  want: "⭐ 想去榜",
  ok: "✨ 可接受榜",
  refuse: "🚫 不去榜",
};

interface Props {
  items: RankItem[];
  pref: Record<PrefLevel, string[]>;
  onChange: (p: Record<PrefLevel, string[]>) => void;
  busy?: boolean;
  bandTitles?: Partial<Record<PrefLevel, string>>;
  searchPlaceholder?: string;
  showCategories?: boolean;
  showRefuse?: boolean;
  emptyText?: string;
  label?: string;
  hint?: string;
  /** 榜单渲染在搜索区上方(true)还是下方(false,默认) */
  boardFirst?: boolean;
  /** 是否渲染「label + hint」标题块(默认 true;POI 意愿页关掉) */
  showLabel?: boolean;
}

export default function RankBoard({
  items,
  pref,
  onChange,
  busy,
  bandTitles,
  searchPlaceholder = "🔍 搜索…",
  showCategories = true,
  showRefuse = true,
  emptyText = "没有匹配项,换个词试试",
  label = "我的优先榜",
  hint = "拖到榜单任意位置 · 榜内拖动换位 · 点 ✕ 移出",
  boardFirst = false,
  showLabel = true,
}: Props) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("全部");
  // 正在拖动的 id + 落点提示(用于画蓝色落点线)
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropHint, setDropHint] = useState<{ band: PrefLevel; index: number } | null>(null);

  const titles = { ...DEFAULT_TITLES, ...(bandTitles ?? {}) };
  const byId = useMemo(() => Object.fromEntries(items.map((p) => [p.id, p])), [items]);

  /** 分类来源:POI 用 tags,偏好标签用 category */
  const categories = useMemo(() => {
    if (!showCategories) return ["全部"];
    const counts = new Map<string, number>();
    items.forEach((p) => {
      const keys = p.category ? [p.category] : p.tags ?? [];
      keys.forEach((t) => counts.set(t, (counts.get(t) ?? 0) + 1));
    });
    return ["全部", ...[...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([t]) => t)];
  }, [items, showCategories]);

  /** 分类展示名:偏好标签的 category 是 key,映射回类别中文名 */
  const catLabel = (key: string) => {
    if (key === "全部") return "全部";
    const hit = items.find((i) => i.category === key);
    return hit?.meta && hit.meta !== key ? hit.meta : key;
  };

  const pool = useMemo(() => {
    const k = q.trim().toLowerCase();
    return items.filter((p) => {
      const inCat = cat === "全部" || (p.category ?? "") === cat || (p.tags ?? []).includes(cat);
      if (!inCat) return false;
      if (!k) return true;
      return (
        p.name.toLowerCase().includes(k) ||
        (p.aliases ?? []).some((a) => a.toLowerCase().includes(k)) ||
        (p.tags ?? []).some((t) => t.includes(k)) ||
        (p.meta ?? "").includes(k)
      );
    });
  }, [items, q, cat]);

  const tierOf = (id: string): PrefLevel | undefined => ORDER.find((lv) => pref[lv].includes(id));

  /** 所有写操作都先做跨层去重,保证同一 id 只出现一次 */
  const commit = (draft: Record<PrefLevel, string[]>) => {
    const seen = new Set<string>();
    const next = {} as Record<PrefLevel, string[]>;
    for (const lv of ORDER) {
      next[lv] = draft[lv].filter((x) => {
        if (seen.has(x)) return false;
        seen.add(x);
        return true;
      });
    }
    onChange(next);
  };

  /** 核心写操作:把 id 放进 band 的 index 处(自动从原榜移除)。index 越界会被夹取。
   *  同榜内换位时,若原位置在目标之前,移除后目标要 -1,否则会"让位"错一格。 */
  const insertInto = (band: PrefLevel, id: string, index: number) => {
    const srcBand = ORDER.find((lv) => pref[lv].includes(id));
    const draft = {} as Record<PrefLevel, string[]>;
    ORDER.forEach((lv) => (draft[lv] = pref[lv].filter((x) => x !== id)));
    let target = index;
    if (srcBand === band) {
      const srcIndex = pref[band].indexOf(id);
      if (srcIndex < target) target -= 1;
    }
    target = Math.max(0, Math.min(target, draft[band].length));
    draft[band] = [...draft[band].slice(0, target), id, ...draft[band].slice(target)];
    commit(draft);
  };

  /** 追加到榜尾(点按加入 / 拖到整块榜单 / 拖动空区) */
  const moveToBand = (id: string, band: PrefLevel) => insertInto(band, id, Number.MAX_SAFE_INTEGER);

  const promote = (id: string) => {
    const cur = tierOf(id);
    if (!cur || cur === "refuse") {
      moveToBand(id, "ok"); // 从不去里移除 → 可接受
      return;
    }
    const idx = ORDER.indexOf(cur);
    if (idx <= 0) return; // 已经最高,不升
    moveToBand(id, ORDER[idx - 1]);
  };

  const reorder = (band: PrefLevel, from: number, to: number) => {
    if (from === to) return;
    insertInto(band, pref[band][from], to);
  };

  const removeItem = (id: string) => {
    const next = {} as Record<PrefLevel, string[]>;
    ORDER.forEach((lv) => (next[lv] = pref[lv].filter((x) => x !== id)));
    onChange(next);
  };

  const clearDrag = () => {
    setDragId(null);
    setDropHint(null);
  };

  /** 按鼠标在半行上的相对位置决定"插到这一行之前还是之后" */
  const indexAtRow = (e: React.DragEvent, i: number) => {
    const r = e.currentTarget.getBoundingClientRect();
    return e.clientY > r.top + r.height / 2 ? i + 1 : i;
  };
  const isHint = (band: PrefLevel, idx: number) => dropHint?.band === band && dropHint.index === idx;

  const overRow = (band: PrefLevel, i: number) => (e: React.DragEvent) => {
    if (!dragId) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setDropHint({ band, index: indexAtRow(e, i) });
  };
  const dropRow = (band: PrefLevel, i: number) => (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragId) insertInto(band, dragId, indexAtRow(e, i));
    clearDrag();
  };
  const overTail = (band: PrefLevel) => (e: React.DragEvent) => {
    if (!dragId) return;
    e.preventDefault();
    e.stopPropagation();
    setDropHint({ band, index: pref[band].length });
  };
  const dropTail = (band: PrefLevel) => (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragId) insertInto(band, dragId, pref[band].length);
    clearDrag();
  };

  const bands = showRefuse ? ORDER : ORDER.filter((lv) => lv !== "refuse");

  // ---------------- 榜单(四段) ----------------
  const boardEl = (
    <div className="rb-board">
      {bands.map((band) => {
        const rows = pref[band];
        return (
          <section
            key={band}
            className={`rb-band ${band}`}
            onDragOver={(e) => {
              if (!dragId) return;
              e.preventDefault();
              setDropHint({ band, index: rows.length }); // 落到行间空档/榜头 → 追加到末尾
            }}
            onDrop={dropTail(band)}
          >
            <div className="rb-band-head">
              <span className={`rb-band-title ${band}`}>{titles[band]}</span>
              <span className="rb-band-count">{rows.length}</span>
            </div>
            {rows.length === 0 ? (
              <div className="rb-band-empty" onDragOver={overTail(band)} onDrop={dropTail(band)}>
                把项目拖到这里
              </div>
            ) : (
              <ul className="rb-rows">
                {rows.map((id, i) => (
                  <Fragment key={id}>
                    {isHint(band, i) && <li className="rb-drop-line" />}
                    <li
                      className="rb-row"
                      draggable={!busy}
                      onDragStart={(e) => {
                        setDragId(id);
                        e.dataTransfer.setData("text/plain", id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={clearDrag}
                      onDragOver={overRow(band, i)}
                      onDrop={dropRow(band, i)}
                      onClick={() => !busy && promote(id)}
                      title="点按升一格 / 拖到别的榜单 / 榜内拖动换位"
                    >
                      <span className="rb-rank">#{i + 1}</span>
                      <span className="rb-row-emoji">{byId[id]?.emoji ?? "🏷️"}</span>
                      <span className="rb-row-name">{byId[id]?.name ?? id}</span>
                      <span className="rb-row-tools">
                        <button
                          className="rb-row-btn"
                          title="榜内上移"
                          onClick={(e) => {
                            e.stopPropagation();
                            reorder(band, i, i - 1);
                          }}
                        >
                          ↑
                        </button>
                        <button
                          className="rb-row-btn"
                          title="榜内下移"
                          onClick={(e) => {
                            e.stopPropagation();
                            reorder(band, i, i + 1);
                          }}
                        >
                          ↓
                        </button>
                        <button
                          className="rb-row-btn del"
                          title="移出榜单"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeItem(id);
                          }}
                        >
                          ✕
                        </button>
                      </span>
                    </li>
                  </Fragment>
                ))}
                {isHint(band, rows.length) && <li className="rb-drop-line" />}
              </ul>
            )}
            {/* 榜尾拖放区:让"拖到末尾"有真实的落点 */}
            <div className="rb-band-tail" onDragOver={overTail(band)} onDrop={dropTail(band)} />
          </section>
        );
      })}
    </div>
  );

  // ---------------- 搜索区(输入 + 分类 + 卡片池) ----------------
  const searchEl = (
    <>
      <input
        className="field rb-search"
        placeholder={searchPlaceholder}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {showCategories && (
        <div className="rb-cats">
          {categories.map((c) => (
            <button key={c} className={`rb-cat ${cat === c ? "active" : ""}`} onClick={() => setCat(c)}>
              {catLabel(c)}
            </button>
          ))}
        </div>
      )}
      <div className="rb-pool">
        {pool.slice(0, 30).map((p) => {
          const tier = tierOf(p.id);
          const inBoard = !!tier;
          return (
            <div
              key={p.id}
              className={`rb-card ${inBoard ? "in-board" : ""} ${tier === "refuse" ? "refused" : ""}`}
              draggable={!inBoard && !busy}
              onDragStart={() => setDragId(p.id)}
              onDragEnd={clearDrag}
              onClick={() => !inBoard && !busy && moveToBand(p.id, "ok")}
              title={inBoard ? "已在榜单,可在榜单内拖动换位" : "点按加入「可接受」,或拖到榜单指定位置"}
            >
              <span className="rb-card-emoji">{p.emoji ?? "🏷️"}</span>
              <div className="rb-card-main">
                <div className="rb-card-name">{p.name}</div>
                {p.meta && <div className="rb-card-meta">{p.meta}</div>}
              </div>
              {showRefuse && (
                <button
                  className={`rb-refuse ${tier === "refuse" ? "on" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    moveToBand(p.id, tier === "refuse" ? "ok" : "refuse");
                  }}
                  title="标为「不去/避免」"
                >
                  {tier === "refuse" ? "✓" : "🙅"}
                </button>
              )}
            </div>
          );
        })}
        {pool.length === 0 && <div className="rb-empty">{emptyText}</div>}
      </div>
    </>
  );

  const labelEl = showLabel ? (
    <div className="rb-label">
      <b>{label}</b>
      <span className="muted small">{hint}</span>
    </div>
  ) : null;

  return (
    <div className={`rb ${boardFirst ? "board-first" : ""}`}>
      {boardFirst ? (
        <>
          {boardEl}
          <div className="rb-search-wrap">
            {labelEl}
            {searchEl}
          </div>
        </>
      ) : (
        <>
          {searchEl}
          {labelEl}
          {boardEl}
        </>
      )}
    </div>
  );
}

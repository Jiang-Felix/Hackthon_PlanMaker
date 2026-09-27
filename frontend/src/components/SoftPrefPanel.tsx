import { useMemo, useState } from "react";
import { PreferenceVocab, PrefLevel, RankItem, TagPref } from "../types";
import RankBoard from "./RankBoard";

/**
 * 「偏好意愿」栏 —— 每人除景点意愿外的模糊软偏好(体力/天气/作息/消费…)。
 *
 * 复用 RankBoard 的「分类搜索 + 四段榜单」交互:上方按类别切页,下方对当前类别的
 * 标签做排序。所有类别共享同一份扁平 TagPref(标签 id 全局唯一)。
 */
const SOFT_TITLES: Record<PrefLevel, string> = {
  must: "❗一定要",
  want: "👍倾向",
  ok: "🙂可以",
  refuse: "🚫避免",
};

interface Props {
  soft: TagPref;
  vocab: PreferenceVocab | null;
  onChange: (p: TagPref) => void;
  busy?: boolean;
}

export default function SoftPrefPanel({ soft, vocab, onChange, busy }: Props) {
  const [catIdx, setCatIdx] = useState(0);

  const cats = vocab?.categories ?? [];

  const items: RankItem[] = useMemo(() => {
    const cat = cats[catIdx];
    if (!cat) return [];
    return cat.tags.map((t) => ({
      id: t.id,
      name: t.label,
      emoji: cat.emoji,
      meta: cat.label,
      category: cat.key,
      aliases: t.aliases,
    }));
  }, [cats, catIdx]);

  const chosen = useMemo(() => {
    const labelOf: Record<string, string> = {};
    cats.forEach((c) => c.tags.forEach((t) => (labelOf[t.id] = t.label)));
    const out: Record<PrefLevel, string[]> = { must: [], want: [], ok: [], refuse: [] };
    (Object.keys(out) as PrefLevel[]).forEach((lv) => {
      out[lv] = (soft?.[lv] ?? []).map((id) => labelOf[id] ?? id);
    });
    return out;
  }, [soft, cats]);

  const total = (Object.values(chosen) as string[][]).reduce((n, arr) => n + arr.length, 0);

  if (!cats.length) return <div className="muted small">词表加载中…</div>;

  return (
    <div className="soft-panel">
      <div className="rb-cats">
        {cats.map((c, i) => (
          <button
            key={c.key}
            className={`rb-cat ${i === catIdx ? "active" : ""}`}
            onClick={() => setCatIdx(i)}
          >
            {c.emoji} {c.label}
          </button>
        ))}
      </div>

      <RankBoard
        items={items}
        pref={soft ?? { must: [], want: [], ok: [], refuse: [] }}
        onChange={onChange}
        busy={busy}
        bandTitles={SOFT_TITLES}
        showCategories={false}
        label={`${cats[catIdx].emoji} ${cats[catIdx].label}`}
        hint="点按升格;↑↓ 排序;✕ 移出"
        emptyText="该类别暂无可选标签"
      />

      {total > 0 && (
        <div className="soft-summary">
          <span className="muted small">已表达 {total} 项偏好:</span>
          <div className="chips">
            {(Object.keys(chosen) as PrefLevel[]).map((lv) =>
              chosen[lv].map((label) => (
                <span key={lv + label} className={`chip ${lv}`}>
                  {label}
                </span>
              )),
            )}
          </div>
        </div>
      )}
    </div>
  );
}
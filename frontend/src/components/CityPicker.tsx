import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { CITY_META } from "../types";

interface Option {
  id: string;
  name: string;
  emoji: string;
}

/**
 * 可搜索的城市选择器(类似其他平台的学校 / 地区选择):关键字过滤 + 范围列表。
 *
 * 选项来自后端 `GET /api/cities` —— 新增一个城市数据文件即自动出现在列表里(可拓展);
 * 显示名优先取本地 CITY_META 元数据,缺失时回退到城市标识。
 */
export default function CityPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const [ids, setIds] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api
      .getCities()
      .then((d) => setIds(d.cities))
      .catch(() => setIds(Object.keys(CITY_META)));
  }, []);

  // 点面板外部收起
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const options = useMemo<Option[]>(
    () => ids.map((id) => ({ id, name: CITY_META[id]?.name ?? id, emoji: CITY_META[id]?.emoji ?? "📍" })),
    [ids],
  );

  const kw = q.trim().toLowerCase();
  const filtered = kw
    ? options.filter((o) => o.name.toLowerCase().includes(kw) || o.id.toLowerCase().includes(kw))
    : options;

  const cur = options.find((o) => o.id === value);

  return (
    <div className="city-picker" ref={boxRef}>
      <button type="button" className={`picker-trigger ${open ? "open" : ""}`} onClick={() => setOpen((v) => !v)}>
        <span className="city-emoji">{cur?.emoji ?? "📍"}</span>
        <span className="picker-cur">{cur?.name ?? value}</span>
        <span className="picker-caret">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="picker-panel">
          <input
            className="field picker-search"
            autoFocus
            placeholder="输入关键字搜索目的地…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="picker-list">
            {filtered.length === 0 ? (
              <div className="picker-empty muted small">没有匹配的目的地</div>
            ) : (
              filtered.map((o) => (
                <button
                  type="button"
                  key={o.id}
                  className={`picker-item ${o.id === value ? "active" : ""}`}
                  onClick={() => {
                    onChange(o.id);
                    setOpen(false);
                    setQ("");
                  }}
                >
                  <span className="city-emoji">{o.emoji}</span>
                  <span className="picker-item-name">{o.name}</span>
                  {o.id === value && <span className="picker-check">✓</span>}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

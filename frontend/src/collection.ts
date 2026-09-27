import type { POI } from "./types";

/** 图鉴页 POI 分组方式:不分组 / 按类型 / 按人均价格 / 按开放时段。 */
export type CollectionGroupBy = "none" | "type" | "price" | "open";

export interface CollectionGroup {
  key: string;
  label: string;
  items: POI[];
}

export const GROUP_OPTIONS: { value: CollectionGroupBy; label: string }[] = [
  { value: "none", label: "不分组" },
  { value: "type", label: "按类型分组" },
  { value: "price", label: "按人均价格分组" },
  { value: "open", label: "按开放时段分组" },
];

/**
 * 「按类型」分组的优先级(第一个命中即归属,保证每处 POI 唯一且稳定)。
 * 桶按更具体的主题排前,避免「亲子/美食」这类可泛标签把专类吸走。
 */
const TYPE_BUCKETS: { key: string; label: string; match: (tags: string[]) => boolean }[] = [
  { key: "art", label: "🖼️ 文博艺术", match: (t) => t.some((x) => ["逛展", "博物馆", "艺术", "文创", "图书馆", "考古"].includes(x)) },
  { key: "science", label: "🔭 科普科技", match: (t) => t.includes("科普") },
  { key: "landmark", label: "🌃 观景地标", match: (t) => t.some((x) => ["观景", "夜景"].includes(x)) },
  { key: "nature", label: "🌳 自然户外", match: (t) => t.some((x) => ["户外", "公园", "赏花", "园林", "古镇", "湖泊", "田园", "竹林", "徒步", "骑行"].includes(x)) },
  { key: "history", label: "🏛️ 历史人文", match: (t) => t.some((x) => ["寺庙", "历史", "道教"].includes(x)) },
  { key: "family", label: "🎠 亲子乐园", match: (t) => t.some((x) => ["乐园", "海洋馆", "亲子"].includes(x)) },
  { key: "shopping", label: "🛍️ 购物", match: (t) => t.includes("购物") },
  { key: "food", label: "🍜 美食", match: (t) => t.includes("美食") },
  { key: "street", label: "☕ 街巷漫步", match: (t) => t.some((x) => ["街区", "咖啡"].includes(x)) },
  { key: "other", label: "🏷️ 其他", match: () => true },
];

/** 「按人均价格」分档(元):免费 / 低 / 中 / 高。 */
const PRICE_BUCKETS: { key: string; label: string; test: (price: number) => boolean }[] = [
  { key: "free", label: "💸 免费", test: (p) => p === 0 },
  { key: "cheap", label: "🎫 ¥1–50", test: (p) => p > 0 && p <= 50 },
  { key: "mid", label: "🎟️ ¥51–150", test: (p) => p > 50 && p <= 150 },
  { key: "premium", label: "👑 ¥150+", test: (p) => p > 150 },
];

/** 「按开放时段」分档:按闭馆时间判别,方便安排日间 / 晚间 / 夜游。 */
const OPEN_BUCKETS: { key: string; label: string; test: (closeHour: number | null) => boolean }[] = [
  { key: "day", label: "☀️ 日间(≤17:00 闭馆)", test: (h) => h !== null && h <= 17 },
  { key: "evening", label: "🌆 晚间(17:00–20:00 闭馆)", test: (h) => h !== null && h > 17 && h <= 20 },
  { key: "night", label: "🌙 夜游(>20:00 仍开放)", test: (h) => h !== null && h > 20 },
  { key: "unknown", label: "❔ 时段未知", test: (h) => h === null },
];

/** 从 "10:00-18:00" 这类开放字符串取闭馆小时;解析不到返回 null。 */
function closeHourOf(open: string): number | null {
  const m = /-\s*(\d{1,2}):\d{2}/.exec(open ?? "");
  if (!m) return null;
  const h = Number(m[1]);
  return Number.isFinite(h) ? h : null;
}

/** 把 POI 列表按所选方式分组;不分组时返回单组,空组不出现。 */
export function groupPois(pois: POI[], groupBy: CollectionGroupBy): CollectionGroup[] {
  if (groupBy === "none") {
    return [{ key: "all", label: "", items: pois }];
  }
  let buckets: CollectionGroup[];
  if (groupBy === "type") {
    buckets = TYPE_BUCKETS.map((b) => ({ key: b.key, label: b.label, items: [] }));
    for (const p of pois) {
      const b = TYPE_BUCKETS.find((x) => x.match(p.tags ?? [])) ?? TYPE_BUCKETS[TYPE_BUCKETS.length - 1];
      buckets.find((g) => g.key === b.key)!.items.push(p);
    }
  } else if (groupBy === "price") {
    buckets = PRICE_BUCKETS.map((b) => ({ key: b.key, label: b.label, items: [] }));
    for (const p of pois) {
      const b = PRICE_BUCKETS.find((x) => x.test(p.price)) ?? PRICE_BUCKETS[PRICE_BUCKETS.length - 1];
      buckets.find((g) => g.key === b.key)!.items.push(p);
    }
  } else {
    buckets = OPEN_BUCKETS.map((b) => ({ key: b.key, label: b.label, items: [] }));
    for (const p of pois) {
      const h = closeHourOf(p.open);
      const b = OPEN_BUCKETS.find((x) => x.test(h)) ?? OPEN_BUCKETS[OPEN_BUCKETS.length - 1];
      buckets.find((g) => g.key === b.key)!.items.push(p);
    }
  }
  return buckets.filter((g) => g.items.length > 0);
}
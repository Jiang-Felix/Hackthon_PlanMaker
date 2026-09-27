import { useEffect, useState } from "react";
import { api } from "../api/client";
import { CITY_META, CheckInRecord, POI } from "../types";
import { CollectionGroupBy, groupPois, GROUP_OPTIONS } from "../collection";

const CITIES = ["shanghai", "hangzhou", "chengdu"] as const;

/** 读取持久化的展示偏好;取失败退回默认值。 */
function loadPref(key: string, dft: string): string {
  try {
    const v = localStorage.getItem(key);
    return v === null || v === "" ? dft : v;
  } catch {
    return dft;
  }
}
function savePref(key: string, val: string) {
  try {
    localStorage.setItem(key, val);
  } catch {
    /* 隐私模式等忽略 */
  }
}

function PoiCard({
  p,
  rec,
  open,
  onOpen,
  onToggle,
}: {
  p: POI;
  rec?: CheckInRecord;
  open: boolean;
  onOpen: () => void;
  onToggle: (visited: boolean) => void;
}) {
  const visited = (rec?.count ?? 0) > 0;
  return (
    <div
      className={`collect-card ${visited ? "visited" : ""} ${open ? "open" : ""}`}
      onClick={onOpen}
    >
      <div className="collect-emoji">{visited ? p.emoji : "❔"}</div>
      <div className={`collect-name ${visited ? "" : "mystery"}`}>{p.name}</div>
      {visited ? (
        <button
          className="collect-btn on"
          title="取消打卡"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(false);
          }}
        >
          ✓ 已打卡
        </button>
      ) : (
        <button
          className="collect-btn"
          title="标记为已去过"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(true);
          }}
        >
          打卡
        </button>
      )}
      {open && (
        <div className="collect-detail muted small">
          <div>
            开放 {p.open} · {p.hours}h · {p.price > 0 ? `¥${p.price}` : "免费"}
          </div>
          <div>{p.desc}</div>
          {visited && rec && rec.count > 1 && <div>去过 {rec.count} 次(首见 {rec.first_at.slice(0, 10)})</div>}
        </div>
      )}
    </div>
  );
}

export default function HomeCollection() {
  const [records, setRecords] = useState<Record<string, CheckInRecord>>({});
  const [poiMap, setPoiMap] = useState<Record<string, POI[]>>({});
  const [openPoi, setOpenPoi] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // 默认:未打卡城市不隐藏、「未打卡地点」隐藏、不分组。
  const [hideEmptyCity, setHideEmptyCity] = useState(() => loadPref("collect.hideEmptyCity", "0") === "1");
  const [hideUnvisited, setHideUnvisited] = useState(() => loadPref("collect.hideUnvisited", "1") === "1");
  const [groupBy, setGroupBy] = useState<CollectionGroupBy>(() => loadPref("collect.groupBy", "none") as CollectionGroupBy);
  /** 城市级展开覆盖:true=展开(含未打卡)。缺省时跟随全局「隐藏未打卡地点」开关。 */
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const loadCollection = async () => {
    const d = await api.getCollection();
    const map: Record<string, CheckInRecord> = {};
    d.records.forEach((r) => (map[r.poi_id] = r));
    setRecords(map);
  };

  useEffect(() => {
    Promise.all([
      loadCollection(),
      Promise.all(CITIES.map((c) => api.getPois(c).then((pois) => [c, pois] as const))).then((entries) =>
        setPoiMap(Object.fromEntries(entries)),
      ),
    ])
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const setHideEmptyCityPref = (v: boolean) => {
    setHideEmptyCity(v);
    savePref("collect.hideEmptyCity", v ? "1" : "0");
  };
  const setHideUnvisitedPref = (v: boolean) => {
    setHideUnvisited(v);
    savePref("collect.hideUnvisited", v ? "1" : "0");
    // 全局开关是「批量」控制:改它就把各城市的单独展开状态清掉,统一跟随新值
    setExpanded({});
  };
  const setGroupByPref = (v: CollectionGroupBy) => {
    setGroupBy(v);
    savePref("collect.groupBy", v);
  };

  const toggle = async (id: string, visited: boolean) => {
    try {
      await api.toggleCollection(id, visited);
    } catch {
      /* 失败不阻塞 */
    }
    await loadCollection();
  };

  const visitedOf = (city: string) =>
    (poiMap[city] ?? []).filter((p) => (records[p.id]?.count ?? 0) > 0).length;

  /** 城市当前是否展开(展开 = 连未打卡的一起显示)。无单独设置时跟随全局开关。 */
  const cityExpanded = (city: string) => expanded[city] ?? !hideUnvisited;
  const toggleCity = (city: string) => setExpanded((m) => ({ ...m, [city]: !cityExpanded(city) }));

  const anyCityShown = loaded && CITIES.some((c) => !(hideEmptyCity && visitedOf(c) === 0));

  return (
    <div className="page home-page">
      <div className="page-head">
        <h2>🗺️ 打卡图鉴</h2>
        <p className="muted">行程「已开始」后按天自动打卡;也能点卡片手动点亮。</p>
      </div>

      <div className="collection-tools">
        <button
          className={`tool-chip ${hideEmptyCity ? "active" : ""}`}
          aria-pressed={hideEmptyCity}
          onClick={() => setHideEmptyCityPref(!hideEmptyCity)}
        >
          {hideEmptyCity ? "✓" : "○"} 隐藏未打卡城市
        </button>
        <button
          className={`tool-chip ${hideUnvisited ? "active" : ""}`}
          aria-pressed={hideUnvisited}
          onClick={() => setHideUnvisitedPref(!hideUnvisited)}
        >
          {hideUnvisited ? "✓" : "○"} 隐藏未打卡地点
        </button>
        <select
          className="tool-select"
          value={groupBy}
          onChange={(e) => setGroupByPref(e.target.value as CollectionGroupBy)}
        >
          {GROUP_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {!loaded ? (
        <div className="empty-state muted">加载中…</div>
      ) : !anyCityShown ? (
        <div className="empty-state">
          <span className="big-emoji">📭</span>
          <div>还没有任何打卡记录</div>
          <p className="muted small">可关闭「隐藏未打卡城市」查看全部城市与地点。</p>
        </div>
      ) : (
        CITIES.map((city) => {
          const pois = poiMap[city] ?? [];
          const visitedN = visitedOf(city);
          if (hideEmptyCity && visitedN === 0) return null;
          const pct = pois.length ? Math.round((visitedN / pois.length) * 100) : 0;
          const isOpen = cityExpanded(city);
          const visible = pois.filter((p) => isOpen || (records[p.id]?.count ?? 0) > 0);
          const groups = groupPois(visible, groupBy);
          return (
            <section key={city} className="collection-city">
              <div className="collection-city-head">
                <button
                  className="collection-city-title"
                  aria-expanded={isOpen}
                  title={isOpen ? "收起未打卡地点" : "展开查看全部地点"}
                  onClick={() => toggleCity(city)}
                >
                  <span className="city-caret">{isOpen ? "▾" : "▸"}</span>
                  {CITY_META[city]?.emoji} {CITY_META[city]?.name}
                  {(pois.length - visitedN) > 0 && (
                    <span className="city-rest muted small">{isOpen ? `全部 ${pois.length}` : `未打卡 +${pois.length - visitedN}`}</span>
                  )}
                </button>
                <span className="collection-progress-label muted">
                  已点亮 {visitedN}/{pois.length} · {pct}%
                </span>
              </div>
              {pois.length > 0 && (
                <div className="mini-progress">
                  <div className="mini-progress-fill" style={{ width: `${pct}%` }} />
                </div>
              )}

              {visible.length === 0 ? (
                <div className="collection-empty muted small">
                  <span>未打卡的地点已收起 —— 点上面的城市名展开</span>
                </div>
              ) : (
                groups.map((g) => (
                  <div key={g.key}>
                    {groupBy !== "none" && (
                      <div className="collection-group-label">
                        {g.label}
                        <span>{g.items.length}</span>
                      </div>
                    )}
                    <div className="collection-grid">
                      {g.items.map((p) => (
                        <PoiCard
                          key={p.id}
                          p={p}
                          rec={records[p.id]}
                          open={openPoi === p.id}
                          onOpen={() => setOpenPoi(openPoi === p.id ? null : p.id)}
                          onToggle={(v) => toggle(p.id, v)}
                        />
                      ))}
                    </div>
                  </div>
                ))
              )}
            </section>
          );
        })
      )}
    </div>
  );
}
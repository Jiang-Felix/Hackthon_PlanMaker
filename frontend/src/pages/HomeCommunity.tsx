import { useEffect, useState } from "react";
import { api } from "../api/client";
import { CITY_META, Post } from "../types";

const CITIES = ["shanghai", "hangzhou", "chengdu"] as const;

/**
 * 社区信息流。内容是**只读的沉淀**:帖子只能来自「管理」页行程卡片的「📤 分享」,
 * 所以这里不再有发帖入口。
 */
export default function HomeCommunity({ refreshKey }: { refreshKey: number }) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [poiMap, setPoiMap] = useState<Record<string, { name: string; emoji: string }>>({});
  const [openComments, setOpenComments] = useState<Set<string>>(new Set());
  const [cmt, setCmt] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");

  const load = () => api.getPosts().then(setPosts).catch((e) => setErr(e instanceof Error ? e.message : String(e)));

  useEffect(() => {
    load();
    // 全部城市的 POI 名,用于渲染帖子挂的景点卡片
    Promise.all(CITIES.map((c) => api.getPois(c))).then((byCity) => {
      const m: Record<string, { name: string; emoji: string }> = {};
      byCity.forEach((ps) => ps.forEach((p) => (m[p.id] = { name: p.name, emoji: p.emoji })));
      setPoiMap(m);
    });
    // refreshKey 变化 = 刚发布完一帖,回到信息流要看到最新的
  }, [refreshKey]);

  const like = async (id: string) => {
    await api.likePost(id).catch(() => {});
    await load();
  };

  const comment = async (id: string) => {
    const t = (cmt[id] ?? "").trim();
    if (!t) return;
    await api.addComment(id, t).catch(() => {});
    setCmt({ ...cmt, [id]: "" });
    await load();
  };

  const toggleComments = (id: string) => {
    const s = new Set(openComments);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    setOpenComments(s);
  };

  return (
    <div className="page home-page">
      <div className="page-head">
        <h2>🏘️ 旅行社区</h2>
        <p className="muted">这里都是同行的人分享的行程 —— 想发帖就去「管理」页,在行程卡片上点「📤 分享」。</p>
      </div>
      {err && <div className="error-banner">⚠️ {err}</div>}

      {posts.length === 0 ? (
        <div className="card empty-state">
          <div className="big-emoji">📭</div>
          <p>还没有人分享 —— 去「管理」页,在你的行程卡片上点「📤 分享」</p>
        </div>
      ) : (
        posts.map((p) => (
          <div key={p.id} className="card post-card">
            <div className="post-head">
              <span className="avatar">{p.avatar}</span>
              <b>{p.author}</b>
              <span className="muted small">
                {CITY_META[p.city]?.name ?? p.city} · {p.created_at.slice(0, 10)}
              </span>
              {p.trip_id && <span className="trip-tag">来自行程</span>}
            </div>
            {p.text && <p className="post-text">{p.text}</p>}

            {(p.sections ?? []).map((s, i) => (
              <div key={i} className="post-section">
                <div className="section-head">
                  <span className="section-kind">{s.kind === "poi" ? "📍" : "📅"}</span>
                  <b>{s.title}</b>
                  {s.subtitle && <span className="muted small">{s.subtitle}</span>}
                </div>
                {s.note && <p className="section-note">{s.note}</p>}
                {s.photos.length > 0 && (
                  <div className="photo-grid">
                    {s.photos.map((ph, j) => (
                      <img key={ph.id || j} className="photo-thumb" src={ph.data} loading="lazy" alt={s.title} />
                    ))}
                  </div>
                )}
              </div>
            ))}

            {p.poi_ids.length > 0 && (
              <div className="chips">
                {p.poi_ids.map((pid) => (
                  <span key={pid} className="chip">
                    {poiMap[pid]?.emoji ?? "📍"} {poiMap[pid]?.name ?? pid}
                  </span>
                ))}
              </div>
            )}

            <div className="post-tools">
              <button className={`btn btn-ghost btn-sm ${p.liked ? "liked" : ""}`} onClick={() => like(p.id)}>
                ♥ {p.likes}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => toggleComments(p.id)}>
                💬 {(p.comments?.length ?? 0)} 条评论
              </button>
            </div>

            {openComments.has(p.id) && (
              <div className="comment-box">
                {(p.comments ?? []).map((c) => (
                  <div key={c.id} className="comment-row">
                    <b>{c.author}</b> <span>{c.text}</span>
                  </div>
                ))}
                <div className="comment-add">
                  <input
                    className="field"
                    placeholder="说点什么…"
                    value={cmt[p.id] ?? ""}
                    onChange={(e) => setCmt({ ...cmt, [p.id]: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && comment(p.id)}
                  />
                  <button className="btn btn-primary btn-sm" onClick={() => comment(p.id)}>
                    发送
                  </button>
                </div>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

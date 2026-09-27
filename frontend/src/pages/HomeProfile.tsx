import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Profile } from "../types";

const AVATARS = ["🧭", "🐼", "🐣", "🦁", "🌸", "🧑‍🎤"];

export default function HomeProfile() {
  const [p, setP] = useState<Profile | null>(null);
  const [edit, setEdit] = useState<Profile | null>(null);
  const [stats, setStats] = useState({ trips: 0, checkins: 0, posts: 0 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    const [prof, col, trips, posts] = await Promise.all([
      api.getProfile(),
      api.getCollection(),
      api.getTrips(),
      api.getPosts(),
    ]);
    setP(prof);
    setEdit(prof);
    setStats({
      trips: trips.length,
      checkins: col.records.filter((r) => r.count > 0).length,
      posts: posts.length,
    });
  };

  useEffect(() => {
    load().catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  const save = async () => {
    if (!edit) return;
    setBusy(true);
    setErr("");
    try {
      const saved = await api.patchProfile({ name: edit.name, avatar: edit.avatar, bio: edit.bio });
      setP(saved);
      setEdit(saved);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!p || !edit) {
    return (
      <div className="page home-page">
        <div className="muted">加载中…</div>
      </div>
    );
  }

  return (
    <div className="page home-page">
      <div className="page-head">
        <h2>👤 个人中心</h2>
      </div>
      {err && <div className="error-banner">⚠️ {err}</div>}

      <div className="card profile-card">
        <div className="profile-avatar-row">
          {AVATARS.map((a) => (
            <button
              key={a}
              className={`avatar-pick ${edit.avatar === a ? "active" : ""}`}
              onClick={() => setEdit({ ...edit, avatar: a })}
            >
              {a}
            </button>
          ))}
        </div>
        <label className="field-label">昵称</label>
        <input className="field" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
        <label className="field-label">简介</label>
        <textarea className="nl-input" rows={2} value={edit.bio} onChange={(e) => setEdit({ ...edit, bio: e.target.value })} />
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={save}>
          {busy ? "保存中…" : "保存"}
        </button>
      </div>

      <div className="stats-row">
        <div className="stat-card">
          <b>{stats.trips}</b>
          <span>行程</span>
        </div>
        <div className="stat-card">
          <b>{stats.checkins}</b>
          <span>打卡</span>
        </div>
        <div className="stat-card">
          <b>{stats.posts}</b>
          <span>发帖</span>
        </div>
      </div>
    </div>
  );
}
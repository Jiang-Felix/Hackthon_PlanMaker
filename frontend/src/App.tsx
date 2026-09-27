import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import BottomNav, { HomeTab } from "./components/BottomNav";
import Setup from "./pages/Setup";
import Preferences from "./pages/Preferences";
import PlanView from "./pages/PlanView";
import FairnessView from "./pages/FairnessView";
import SettingsView from "./pages/SettingsView";
import HomeCommunity from "./pages/HomeCommunity";
import HomeCollection from "./pages/HomeCollection";
import HomeManage from "./pages/HomeManage";
import HomeProfile from "./pages/HomeProfile";
import PostComposer from "./pages/PostComposer";
import { CITY_META, Trip } from "./types";

type TripTab = "prefs" | "settings" | "plan" | "fairness";
type Screen = "home" | "creating" | "trip" | "composing";

export default function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [homeTab, setHomeTab] = useState<HomeTab>("manage");
  const [trip, setTrip] = useState<Trip | null>(null);
  const [tripTab, setTripTab] = useState<TripTab>("prefs");
  /** 正在分享的行程(「管理」页行程卡片的 📤 分享 → 发帖编辑界面) */
  const [composeTrip, setComposeTrip] = useState<Trip | null>(null);
  /** 发布后自增,驱动社区信息流重新拉取(看到刚发的帖) */
  const [feedKey, setFeedKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [appErr, setAppErr] = useState<string | null>(null);
  const [resumed, setResumed] = useState(false);
  const [aiReady, setAiReady] = useState<boolean | null>(null);
  const [aiReason, setAiReason] = useState<string>("");

  const checkHealth = useCallback(async () => {
    try {
      const h = await api.getHealth();
      setAiReady(h.ready);
      if (!h.ready) {
        setAiReason(
          h.provider === "mock"
            ? "演示环境未接入 AI,只能整理偏好、暂时无法生成行程。"
            : h.reason ?? "AI 服务暂时不可用。",
        );
      }
    } catch {
      setAiReady(null);
    }
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("trip");
    if (id) {
      api
        .getTrip(id)
        .then((t) => {
          setTrip(t);
          setTripTab(t.current_plan ? "plan" : "prefs");
          setScreen("trip");
          window.history.replaceState({}, "", "/");
        })
        .catch(() => {})
        .finally(() => setResumed(true));
    } else {
      setResumed(true);
    }
  }, []);

  /** 回到首页(管理):离开行程工作区 */
  const goHome = useCallback(() => {
    setTrip(null);
    setScreen("home");
    setHomeTab("manage");
    window.history.replaceState({}, "", "/");
  }, []);

  const enterTrip = useCallback((t: Trip) => {
    setTrip(t);
    setTripTab(t.current_plan ? "plan" : "prefs");
    setScreen("trip");
    const url = new URL(window.location.href);
    url.searchParams.set("trip", t.id);
    window.history.replaceState({}, "", url.toString());
  }, []);

  const refresh = useCallback(async () => {
    if (trip) setTrip(await api.getTrip(trip.id));
  }, [trip?.id]);

  const run = useCallback(async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setAppErr(null);
    try {
      await fn();
      after?.();
    } catch (e) {
      // 面向用户的措辞:不出现 uvicorn / 端口 / vite 这类开发信息
      // (失败也可能是后端正常返回的 422,提示"后端没启动"会误导)
      setAppErr("操作没能完成:" + (e instanceof Error ? e.message : String(e)));
    } finally {
      setBusy(false);
    }
  }, []);

  if (!resumed) {
    return <div className="app-loading">加载中…</div>;
  }

  return (
    <div className="app">
      <header className={`app-header ${screen === "trip" || screen === "composing" ? "with-back" : ""}`}>
        {screen === "trip" || screen === "composing" ? (
          <button
            className="back-btn"
            onClick={() => {
              if (screen === "composing") {
                setScreen("home");
                setHomeTab("manage");
              } else {
                goHome();
              }
            }}
          >
            ← 返回
          </button>
        ) : (
          <div className="brand">
            <span className="brand-logo">🧭</span>
            <div>
              <div className="brand-name">行程平衡器</div>
              <div className="brand-sub">和 TA 一起出发</div>
            </div>
          </div>
        )}
        {trip && screen === "trip" && (
          <div className="header-city">
            <span className="city-emoji">{CITY_META[trip.city]?.emoji ?? "📍"}</span>
            {CITY_META[trip.city]?.name ?? trip.city} · {trip.days}天
          </div>
        )}
      </header>

      {aiReady === false && (
        <div className="ai-warning">
          <b>⚠️ AI 暂时不可用</b> —— {aiReason}
          <div className="ai-warning-hint">
            行程生成需要 AI 服务。请确认网络已连接;若持续如此,请联系管理员检查服务配置。
            <button className="ai-warning-retry" onClick={checkHealth}>
              重新检测
            </button>
          </div>
        </div>
      )}

      {screen === "composing" && composeTrip ? (
        <main className="workspace">
          <PostComposer
            trip={composeTrip}
            onBack={() => {
              setScreen("home");
              setHomeTab("manage");
            }}
            onDone={() => {
              // 发布成功:回到社区,并让信息流重新拉取,新帖在最前
              setScreen("home");
              setHomeTab("community");
              setFeedKey((k) => k + 1);
            }}
          />
        </main>
      ) : screen === "creating" ? (
        <Setup
          onCreated={(t) => enterTrip(t)}
          onBack={() => setScreen("home")}
        />
      ) : screen === "trip" && trip ? (
        <main className="workspace">
          {appErr && <div className="error-banner top">⚠️ {appErr}</div>}
          <nav className="tabbar">
            {(
              [
                ["prefs", "偏好"],
                ["settings", "规则"],
                ["plan", "行程"],
                ["fairness", "公平"],
              ] as [TripTab, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                className={`tab ${tripTab === key ? "active" : ""}`}
                onClick={() => setTripTab(key)}
              >
                {label}
              </button>
            ))}
          </nav>

          {busy && <div className="busy-mask"><div className="spinner" /> 计算中…</div>}

          {tripTab === "prefs" && (
            <Preferences trip={trip} onUpdated={refresh} onGoRules={() => setTripTab("settings")} />
          )}
          {tripTab === "settings" && (
            <SettingsView
              trip={trip}
              onUpdated={refresh}
              onPlanReady={() =>
                run(() => api.makePlan(trip.id), () => {
                  refresh().then(() => setTripTab("plan"));
                })
              }
              onOpenPlan={() => setTripTab("plan")}
            />
          )}
          {tripTab === "plan" && <PlanView trip={trip} refresh={refresh} />}
          {tripTab === "fairness" && <FairnessView trip={trip} />}
        </main>
      ) : (
        <main className="workspace home">
          {appErr && <div className="error-banner top">⚠️ {appErr}</div>}
          {homeTab === "community" && <HomeCommunity refreshKey={feedKey} />}
          {homeTab === "collection" && <HomeCollection />}
          {homeTab === "manage" && (
            <HomeManage
              onOpenTrip={enterTrip}
              onShare={(t) => {
                setComposeTrip(t);
                setScreen("composing");
              }}
            />
          )}
          {homeTab === "profile" && <HomeProfile />}
        </main>
      )}

      {screen === "home" && (
        <BottomNav tab={homeTab} onTab={setHomeTab} onCreate={() => setScreen("creating")} />
      )}

      <footer className="app-footer">
        AI HACKATHON · 携程 2026 · 用算法让每一次妥协都被看见
      </footer>
    </div>
  );
}
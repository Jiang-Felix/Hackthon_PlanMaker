import type {
  CheckInRecord,
  CollectionData,
  Comment,
  DayWeather,
  Plan,
  POI,
  Post,
  PostSection,
  PreferenceVocab,
  Profile,
  RecoSettings,
  ReplanResult,
  StructuredPref,
  TagPref,
  Trip,
} from "../types";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  // 超时:后端不可达时 fetch 会立即连接失败(不依赖此值);此值只兜住"请求挂起"。
  // AI 决策端用推理模型时单次规划可能数十秒,故放宽到 180s。
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 180000);
  try {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      signal: ctrl.signal,
      ...init,
    });
    if (!res.ok) {
      // 后端失败时返回结构化 detail(如 422 的校验问题清单),取出可读文案;
      // 取不到(5xx 的 HTML/纯文本、网关错误页)时**不要把原始响应体给用户看** ——
      // 那里面可能是堆栈、HTML 或英文技术信息。
      const raw = await res.text();
      let msg = "";
      try {
        const j = JSON.parse(raw);
        const d = j?.detail;
        if (typeof d === "string") msg = d;
        else if (d?.message) msg = d.message + (d.issues?.length ? "\n· " + d.issues.join("\n· ") : "");
      } catch {
        /* 非 JSON:落到下面的友好兜底 */
      }
      if (!msg) {
        msg = res.status >= 500
          ? "服务暂时不可用,请稍后重试"
          : `请求没能完成(错误码 ${res.status})`;
      }
      throw new Error(msg);
    }
    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("请求超时,请稍后重试");
    }
    // fetch 在网络层失败(TypeError: Failed to fetch)时给用户可读的说明
    if (e instanceof TypeError) {
      throw new Error("网络连接失败,请检查网络后重试");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  createTrip(body: { city: string; days: number; total_budget: number; initial_people?: number; start_at?: string }) {
    return req<Trip>("/api/trip", { method: "POST", body: JSON.stringify(body) });
  },

  /** 后端可用的城市标识列表(新增城市数据文件即自动出现在这里)。 */
  getCities() {
    return req<{ cities: string[] }>("/api/cities");
  },

  addParticipant(
    tripId: string,
    body: {
      name: string;
      natural_text?: string;
      structured?: unknown;
      soft?: unknown;
      merge?: boolean;
      /** 原文仅记入历史,后端不再调用 AI 解析(前端已用 /api/parse/* 解析) */
      already_parsed?: boolean;
    }
  ) {
    return req<Trip>(`/api/trip/${tripId}/participants`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  getVocab() {
    return req<PreferenceVocab>("/api/preference-vocab");
  },

  /** AI 就绪自检:ready=false 表示未配置 DEEPSEEK_API_KEY(无法生成行程)。 */
  getHealth() {
    return req<{ ok: boolean; provider: string; ready: boolean; reason?: string }>("/api/health");
  },

  /** 第一步:自然语言 → 景点意愿(四层 POI 偏好)。 */
  parsePoi(city: string, text: string) {
    return req<StructuredPref>("/api/parse/poi", {
      method: "POST",
      body: JSON.stringify({ city, text }),
    });
  },

  /** 第二步:自然语言 → 扩展软偏好(词表标签)。 */
  parseSoft(text: string) {
    return req<TagPref>("/api/parse/soft", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },

  saveSettings(tripId: string, body: { natural_text?: string; settings?: RecoSettings }) {
    return req<Trip>(`/api/trip/${tripId}/settings`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  /** 行程逐日真实天气(取不到时 days 为空数组)。 */
  getWeather(tripId: string) {
    return req<{ days: DayWeather[] }>(`/api/trip/${tripId}/weather`);
  },

  /** 食宿预算口径:auto=按偏好估计 / manual=手动单价 */
  saveBudget(
    tripId: string,
    body: { mode?: "auto" | "manual"; food_per_head?: number; lodging_per_head?: number }
  ) {
    return req<Trip>(`/api/trip/${tripId}/settings`, {
      method: "PATCH",
      body: JSON.stringify({ budget: body }),
    });
  },

  getPois(city: string) {
    return req<POI[]>(`/api/cities/${city}/pois`);
  },

  getTrip(tripId: string) {
    return req<Trip>(`/api/trip/${tripId}`);
  },

  makePlan(tripId: string) {
    return req<Plan>(`/api/trip/${tripId}/plan`, { method: "POST" });
  },

  replan(
    tripId: string,
    body: {
      participant_id?: string;
      natural_text?: string;
      structured?: unknown;
      current_day?: number;
    }
  ) {
    return req<ReplanResult>(`/api/trip/${tripId}/replan`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  // ---------------------------------------------------------- 五栏外壳
  getTrips() {
    return req<Trip[]>("/api/trips");
  },

  deleteTrip(tripId: string) {
    return req<void>(`/api/trip/${tripId}`, { method: "DELETE" });
  },

  getProfile() {
    return req<Profile>("/api/profile");
  },

  patchProfile(body: Partial<Profile>) {
    return req<Profile>("/api/profile", { method: "PATCH", body: JSON.stringify(body) });
  },

  getCollection() {
    return req<CollectionData>("/api/collection");
  },

  toggleCollection(poiId: string, visited: boolean) {
    return req<CheckInRecord>(`/api/collection/${poiId}`, {
      method: "POST",
      body: JSON.stringify({ visited }),
    });
  },

  getPosts() {
    return req<Post[]>("/api/posts");
  },

  createPost(body: { city: string; text: string; poi_ids: string[]; trip_id?: string; sections?: PostSection[] }) {
    return req<Post>("/api/posts", { method: "POST", body: JSON.stringify(body) });
  },

  likePost(postId: string) {
    return req<Post>(`/api/posts/${postId}/like`, { method: "POST" });
  },

  addComment(postId: string, text: string) {
    return req<Comment>(`/api/posts/${postId}/comments`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },
};
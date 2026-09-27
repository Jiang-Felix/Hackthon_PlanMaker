// 与 backend/app/models.py 对齐的类型

export interface POI {
  id: string;
  name: string;
  emoji: string;
  lat: number;
  lng: number;
  price: number;
  hours: number;
  tags: string[];
  aliases?: string[];
  open: string;
  desc: string;
}

export type PrefLevel = "refuse" | "must" | "want" | "ok";

export interface StructuredPref {
  refuse: string[];
  must: string[];
  want: string[];
  ok: string[];
}

/** 扩展软偏好:与 StructuredPref 同形,但承载的是**词表 tag id**(非 POI id)。 */
export type TagPref = StructuredPref;

/** 全局推荐设置(评审 Recommendation Logic Design)。 */
export interface RecoSettings {
  conflict_strategy: "rotate" | "split" | "majority";
  schedule_align: "left" | "center" | "right" | "fill";
  activity_priorities: string[];
  buffer_min: number;
  max_wait_min: number;
  raw_text: string;
}

/** 词表扁平化后的标签项(后端 VocabTag 镜像)。 */
export interface VocabTag {
  id: string;
  label: string;
  emoji: string;
  category: string;
  category_label: string;
  aliases: string[];
}

export interface VocabOption {
  id: string;
  label: string;
  aliases: string[];
}

export interface PreferenceVocab {
  version: number;
  categories: {
    key: string;
    label: string;
    emoji: string;
    tags: { id: string; label: string; aliases: string[] }[];
  }[];
  reco_options: {
    conflict_strategy: VocabOption[];
    schedule_align: VocabOption[];
    activity_priorities: VocabOption[];
  };
}

/** 榜单可榜项 —— RankBoard 泛化后的统一数据源(POI 与偏好标签共用)。 */
export interface RankItem {
  id: string;
  name: string;
  emoji?: string;
  meta?: string;
  tags?: string[];
  category?: string;
  aliases?: string[];
  desc?: string;
}

export interface Participant {
  id: string;
  name: string;
  natural_text: string;
  /** 自然语言输入历史:[0]=原始输入,后续每次「再补充几句」各一条 */
  natural_inputs: string[];
  pref: StructuredPref;
  soft: TagPref;
}

export interface Trip {
  id: string;
  city: string;
  days: number;
  total_budget: number;
  /** 创建时设定的初始人数(「偏好」页据此预置待填写成员位) */
  initial_people?: number;
  hotel_lat: number;
  hotel_lng: number;
  /** 出发日期时间,本地 ISO "YYYY-MM-DDTHH:MM";无 = 旧行为,永不自动冻结 */
  start_at?: string | null;
  /** 创建时间(ISO,微秒),「管理」列表排序/显示 */
  created_at?: string;
  /** 食宿口径:auto=按成员偏好估计 / manual=规则页手动填 */
  budget_mode?: "auto" | "manual";
  /** 每人每天餐费(元) */
  food_per_head?: number;
  /** 每人每晚住宿(元) */
  lodging_per_head?: number;
  participants: Participant[];
  settings: RecoSettings;
  current_plan: Plan | null;
}

/** 全队花销分项(评审经济计算)。 */
export interface CostBreakdown {
  /** 门票 = Σ(人均门票 × 人数) */
  tickets: number;
  /** 打车合计(全队共享,按趟) */
  transport: number;
  /** 餐饮 = 每人每天 × 人数 × 天 */
  food: number;
  /** 住宿 = 每人每晚 × 人数 × 天 */
  lodging: number;
  per_head_food: number;
  per_head_lodging: number;
}

/** 逐日真实天气(Open-Meteo),供行程页展示;取不到时后端返回空数组。 */
export interface DayWeather {
  date: string;
  icon: string;
  text: string;
  tmax: number | null;
  tmin: number | null;
  precip: number | null;
}

/** 「个人」页资料(单用户)。 */
export interface Profile {
  name: string;
  avatar: string;
  bio: string;
}

/** 图鉴打卡记录:visited = count > 0。 */
export interface CheckInRecord {
  poi_id: string;
  city: string;
  count: number;
  first_at: string;
}

/** 帖子图文段落的两种组织方式:按地点 / 按天。 */
export type PhotoKind = "poi" | "day";

export interface PostPhoto {
  /** 由后端 store 生成(提交时留空)。 */
  id: string;
  /** 客户端压缩后的 data URL(内嵌,无独立上传接口)。 */
  data: string;
  caption: string;
}

/** 帖子的一段:按地点或按天聚合的照片 + 文字评论(title/subtitle 为冗余展示串)。 */
export interface PostSection {
  kind: PhotoKind;
  poi_id: string;
  day: number | null;
  title: string;
  subtitle: string;
  note: string;
  photos: PostPhoto[];
}

/** 社区帖子(内容只来自行程分享)。 */
export interface Post {
  id: string;
  author: string;
  avatar: string;
  city: string;
  text: string;
  created_at: string;
  poi_ids: string[];
  /** 来源行程 id(仅存档;不据此反查,行程删除后帖子仍可渲染)。 */
  trip_id?: string;
  /** 按地点/按天的图文段落;旧响应可能缺省。 */
  sections?: PostSection[];
  likes: number;
  liked: boolean;
  comments?: Comment[];
}

export interface Comment {
  id: string;
  post_id: string;
  author: string;
  text: string;
  created_at: string;
}

export interface CollectionData {
  records: CheckInRecord[];
  progress: Record<string, { visited: number; total: number }>;
}

export interface DayStop {
  poi_id: string;
  name: string;
  emoji: string;
  arrive_min: number;
  start_min: number;
  end_min: number;
  travel_min: number;
  travel_mode: string;
  travel_cost: number;
  price: number;
  tags: string[];
}

export interface DayPlan {
  day: number;
  stops: DayStop[];
  day_spent: number;
  day_end_note: string;
}

export interface Explanation {
  poi_id: string;
  included: boolean;
  title: string;
  reasons: string[];
  who_likes: string[];
  who_conceded: string[];
  level: string;
}

/** 让步的真实原因。只有 `passed_over` 会进 `FairnessReport.concessions`。 */
export type ConcessionKind = "passed_over" | "out_of_capacity" | "refused_by_other";

export interface Concession {
  /** -1 = 只是解释材料(排不下 / 被他人拒绝),不算「谁让了步」。 */
  round: number;
  participant_id: string;
  participant_name: string;
  loser_poi: string;
  kind: ConcessionKind;
  reason: string;
}

/**
 * 一个人的公平账 —— 回答「TA 被牺牲了吗、被牺牲了多少」,而不是「满意度百分之几」。
 *
 * 口径要点(后端 `scheduler/fairness.py` 有精确公式):
 * - `share` 不是占比,可能 >1,也可能为 `null`(= 这人压根没提意愿,显示 N/A,
 *   **绝不可当 0 渲染**)。禁止对 `share` 求平均。
 * - 粒度只有几个名额,一个名额就摆动 33–50%,所以**颜色用整数 `deficit`**,
 *   比率只作文本展示。
 */
export interface FairnessRow {
  participant_id: string;
  name: string;
  must_met: number;
  must_total: number;
  /** 拿到的「有人想要」的名额数。 */
  slots_got: number;
  /** 声明的意愿数(∩ 合法 POI id)。 */
  wants_declared: number;
  /** 应得名额 = min(自己声明的数量, 人头均分)。`null` 同 `share`。 */
  slots_owed: number | null;
  /** 拿到 / 应得,封顶 1;`null` = 未提意愿。 */
  share: number | null;
  /** 整数缺口 max(0, round(应得 - 拿到)) —— 颜色与轮换优先权的依据。 */
  deficit: number;
  soft_declared: number;
  /** 拿到模型裁决的软偏好数(三类之和);0 = 完全未评估(**不是**「全没被照顾」)。 */
  soft_cared: number;
  soft_rate: number | null;
  soft_satisfied: string[];
  soft_missed: string[];
  soft_violated: string[];
  /** 模型**没给出裁决**的已声明标签 —— 非空即自评不完整,必须如实显示。 */
  soft_unaccounted: string[];
  /** 逐层级的 POI id:已满足 / 缺失。前端再查名字渲染。 */
  satisfied: Record<string, string[]>;
  missing: Record<string, string[]>;
  concession_count: number;
}

export interface FairnessReport {
  participants: FairnessRow[];
  concessions: Concession[];
  summary_messages: string[];
  /** 有争议的名额数(至少一人声明过)。 */
  contested_slots: number;
  /** 排进去但没任何人声明过的名额数。 */
  undeclared_slots: number;
  /** 人头均分基数 = contested_slots / 提出意愿的人数。 */
  quota: number;
}

export interface Plan {
  trip_name: string;
  city: string;
  days: DayPlan[];
  explanations: Explanation[];
  fairness: FairnessReport;
  total_spent: number;
  total_budget: number;
  engine?: string;
  cost_breakdown?: CostBreakdown;
}

export interface ReplanResult {
  plan: Plan;
  added: string[];
  removed: string[];
  affected: string[];
}

export const LEVEL_META: Record<PrefLevel, { label: string; color: string; weight: number }> = {
  refuse: { label: "不去", color: "#e5484d", weight: -100 },
  must: { label: "必去", color: "#2e6df6", weight: 10 },
  want: { label: "想去", color: "#f5a623", weight: 4 },
  ok: { label: "可接受", color: "#30a46c", weight: 1 },
};

export const CITY_META: Record<string, { name: string; emoji: string }> = {
  shanghai: { name: "上海", emoji: "🏙️" },
  hangzhou: { name: "杭州", emoji: "🏞️" },
  chengdu: { name: "成都", emoji: "🍜" },
};

export function fmtMinute(m: number): string {
  const h = Math.floor(m / 60) % 24;
  const mm = m % 60;
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}
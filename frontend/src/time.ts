import { Trip } from "./types";

/**
 * 行程「已开始 / 未开始」的时间判定 —— 前端展示用。
 *
 * 后端 `main.py::_current_day_for` 是冻结/重排的**权威**判定(以服务器时钟为准);
 * 这里做同款计算供 UI 显示横幅、日期、冻结徽章,避免每页重复。
 *
 * 口径:start_at 为本地 ISO "YYYY-MM-DDTHH:MM"(无时区,单机一致)。
 * `current_day` = 已完整走完的天数(前 N 天冻结),clamp 到 [0, days-1]。
 */
export interface TimeState {
  /** now >= start_at */
  started: boolean;
  /** 已冻结天数 / 进行到的天下标(0 起)。未开始或无 start_at = 0 */
  current_day: number;
  /** start_at 解析结果;无/非法 = null */
  startedAt: Date | null;
}

const DAY_MS = 86400000;
const WEEK = ["日", "一", "二", "三", "四", "五", "六"];

export function tripTimeState(trip: Trip, now: number = Date.now()): TimeState {
  if (!trip.start_at) return { started: false, current_day: 0, startedAt: null };
  const s = new Date(trip.start_at);
  if (Number.isNaN(s.getTime())) return { started: false, current_day: 0, startedAt: null };
  const elapsed = now - s.getTime();
  if (elapsed < 0) return { started: false, current_day: 0, startedAt: s };
  const day = Math.floor(elapsed / DAY_MS);
  return { started: true, current_day: Math.max(0, Math.min(day, trip.days - 1)), startedAt: s };
}

/** 第 idx 天的真实日期标签,如 "9/27 周六";无 start_at 返回空串(调用方回退"第 N 天")。 */
export function dayDateLabel(trip: Trip, dayIdx: number): string {
  const s = trip.start_at ? new Date(trip.start_at) : null;
  if (!s || Number.isNaN(s.getTime())) return "";
  const d = new Date(s.getTime() + dayIdx * DAY_MS);
  return `${d.getMonth() + 1}/${d.getDate()} 周${WEEK[d.getDay()]}`;
}

/** start_at 的可读展示,如 "9/27 09:00";无则空串。 */
export function fmtStartAt(trip: Trip): string {
  const s = trip.start_at ? new Date(trip.start_at) : null;
  if (!s || Number.isNaN(s.getTime())) return "";
  const hh = String(s.getHours()).padStart(2, "0");
  const mm = String(s.getMinutes()).padStart(2, "0");
  return `${s.getMonth() + 1}/${s.getDate()} ${hh}:${mm}`;
}

export type TripStatus = "upcoming" | "ongoing" | "done";

/** 「管理」列表的状态徽章:未开始 / 进行中 / 已完成(全部天已过完)。 */
export function tripStatus(trip: Trip, now: number = Date.now()): TripStatus {
  if (!trip.start_at) return "upcoming";
  const s = new Date(trip.start_at);
  if (Number.isNaN(s.getTime())) return "upcoming";
  if (now < s.getTime()) return "upcoming";
  if (now - s.getTime() >= trip.days * DAY_MS) return "done";
  return "ongoing";
}
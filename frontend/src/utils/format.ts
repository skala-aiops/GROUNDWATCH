import { labels } from "../constants/status";
export const number = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
export const fmt = (v: unknown, digits = 3) =>
  number(v) ? v.toFixed(digits) : "—";
export const label = (s: unknown) =>
  labels[String(s || "").toLowerCase()] || String(s || "—");

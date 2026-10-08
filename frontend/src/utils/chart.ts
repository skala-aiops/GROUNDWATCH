import type { Row } from "../types/domain";
import { number } from "./format";
export function comparison(actual: unknown, predicted: unknown) {
  if (!number(actual) || !number(predicted)) return "";
  const a = Number(actual.toFixed(3)),
    p = Number(predicted.toFixed(3));
  return a > p ? "above" : a < p ? "below" : "";
}

// A missing calendar date is a gap even when no null row was returned.
export function chartSegments(rows: Row[], key: string) {
  const segments: { index: number; value: number }[][] = [];
  let current: { index: number; value: number }[] = [];
  let previous = NaN;
  rows.forEach((row, index) => {
    const day = Date.parse(row.date + "T00:00:00Z");
    if (!number(row[key]) || !Number.isFinite(day)) {
      if (current.length) segments.push(current);
      current = [];
      previous = NaN;
      return;
    }
    if (current.length && day - previous !== 86400000) {
      segments.push(current);
      current = [];
    }
    current.push({ index, value: row[key] });
    previous = day;
  });
  if (current.length) segments.push(current);
  return segments;
}

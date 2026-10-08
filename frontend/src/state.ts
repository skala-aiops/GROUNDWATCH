import { atom } from "jotai";
export const viewAtom = atom<"overview" | "detail" | "operations">("overview");
export const districtAtom = atom("11110");
export const modeAtom = atom("current");
export const replayAtom = atom(
  new URLSearchParams(location.search).get("replay_id") || "",
);
export const dateAtom = atom("");
export const searchAtom = atom("");
export const rangeAtom = atom(30);
export const threeAtom = atom(true);
export const reducedAtom = atom(
  matchMedia("(prefers-reduced-motion: reduce)").matches,
);

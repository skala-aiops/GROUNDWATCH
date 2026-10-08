import { useEffect, useState } from "react";
import type { Row } from "../types/domain";
import { request } from "../api/client";
export function useResource(
  path: string | null,
  interval = 30000,
  revision = 0,
) {
  const [state, set] = useState<{
    data: Row | null;
    error: string;
    loading: boolean;
  }>({ data: null, error: "", loading: true });
  useEffect(() => {
    let alive = true;
    let controller: AbortController;
    let timer: ReturnType<typeof setTimeout>;
    set({ data: null, error: "", loading: !!path });
    const load = async () => {
      if (!path) return;
      controller = new AbortController();
      try {
        const data = await request(path, { signal: controller.signal });
        if (alive) set({ data, error: "", loading: false });
      } catch (e) {
        if (alive && !(e instanceof DOMException && e.name === "AbortError"))
          set({
            data: null,
            error: String((e as Error).message),
            loading: false,
          });
      } finally {
        if (alive && path) timer = setTimeout(load, interval);
      }
    };
    load();
    return () => {
      alive = false;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [path, interval, revision]);
  return state;
}

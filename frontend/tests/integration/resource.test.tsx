// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useResource } from "../../src/hooks/useResource";
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.useRealTimers();});
it("does not request when disabled",()=>{const fetcher=vi.fn();vi.stubGlobal("fetch",fetcher);const {result}=renderHook(()=>useResource(null));expect(result.current.loading).toBe(false);expect(fetcher).not.toHaveBeenCalled();});
it("aborts the old request and ignores its late response after station change",async()=>{
 let release: (value:Response)=>void=()=>{};const calls:RequestInit[]=[];
 vi.stubGlobal("fetch",vi.fn((url:string,init:RequestInit)=>{calls.push(init);return url.endsWith("/old")?new Promise<Response>(resolve=>{release=resolve;}):Promise.resolve(new Response(JSON.stringify({station_id:"new"})));}));
 const {result,rerender,unmount}=renderHook(({path})=>useResource(path,10000),{initialProps:{path:"/old"}});
 await waitFor(()=>expect(calls.length).toBe(1));rerender({path:"/new"});await waitFor(()=>expect(result.current.data?.station_id).toBe("new"));
 expect(calls[0].signal?.aborted).toBe(true);await act(async()=>{release(new Response(JSON.stringify({station_id:"old"})));});expect(result.current.data?.station_id).toBe("new");unmount();expect(calls[1].signal?.aborted).toBe(true);
});
it("exposes server error and recovers after explicit refresh",async()=>{
 const fetcher=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:"not ready"}),{status:503})).mockImplementation(async()=>new Response(JSON.stringify({ready:true})));vi.stubGlobal("fetch",fetcher);
 const {result,rerender}=renderHook(({revision})=>useResource("/health/ready",10000,revision),{initialProps:{revision:0}});
 await waitFor(()=>expect(result.current.error).toBe("not ready"));expect(result.current.data).toBeNull();rerender({revision:1});await waitFor(()=>expect(result.current.data?.ready).toBe(true));expect(result.current.error).toBe("");
});
it("polls only after the previous response and clears the timer on unmount",async()=>{
 vi.useFakeTimers();const fetcher=vi.fn(async()=>new Response("{}"));vi.stubGlobal("fetch",fetcher);const {unmount}=renderHook(()=>useResource("/stations",1000));await act(async()=>{await vi.advanceTimersByTimeAsync(0);});expect(fetcher).toHaveBeenCalledTimes(1);await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});expect(fetcher).toHaveBeenCalledTimes(2);unmount();await vi.advanceTimersByTimeAsync(5000);expect(fetcher).toHaveBeenCalledTimes(2);
});

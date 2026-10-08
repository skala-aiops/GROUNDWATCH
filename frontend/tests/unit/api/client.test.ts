import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient, post, request } from "../../../src/api/client";
afterEach(() => vi.unstubAllGlobals());
describe("HTTP interceptor contract", () => {
 it("adds JSON Accept and preserves abort signal", async () => {
  const signal=new AbortController().signal; const fetcher=vi.fn(async (..._args: any[])=>new Response("{}"));vi.stubGlobal("fetch",fetcher);
  await createApiClient().request("/stations",{signal});
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/stations");
  const init=fetcher.mock.calls[0][1] as RequestInit;expect(new Headers(init.headers).get("Accept")).toBe("application/json");expect(init.signal).toBe(signal);
 });
 it("preserves validation details and never retries a failed mutation", async () => {
  const detail=[{loc:["body","sequence"],msg:"too short"}];const fetcher=vi.fn(async (..._args: any[])=>new Response(JSON.stringify({detail}),{status:422}));vi.stubGlobal("fetch",fetcher);
  await expect(createApiClient().post("/predict",{})).rejects.toMatchObject({name:"ApiError",status:422,details:detail});expect(fetcher).toHaveBeenCalledTimes(1);
 });
 it("keeps readiness 503 as an API failure", async () => {
  const fetcher=vi.fn(async (..._args: any[])=>new Response(JSON.stringify({detail:"model not ready"}),{status:503}));vi.stubGlobal("fetch",fetcher);
  await expect(createApiClient().request("/health/ready")).rejects.toBeInstanceOf(ApiError);expect(fetcher.mock.calls[0][0]).toBe("/health/ready");
 });
 it("lets the browser set multipart boundary and handles empty success", async()=>{
  const fetcher=vi.fn(async (..._args: any[])=>new Response(null,{status:204}));vi.stubGlobal("fetch",fetcher);
  const body=new FormData();body.append("file",new Blob(["TEST ONLY"]),"fixture.csv");
  expect(await createApiClient().request("/upload",{method:"POST",body,headers:{"Content-Type":"multipart/form-data"}})).toBeUndefined();
  expect(new Headers((fetcher.mock.calls[0][1] as RequestInit).headers).has("Content-Type")).toBe(false);
 });
 it("runs registered interceptors in order and supports removal",async()=>{
  const c=createApiClient();const removed=c.interceptors.request.use(x=>({...x,url:"/wrong"}));c.interceptors.request.eject(removed);
  c.interceptors.request.use(x=>({...x,init:{...x.init,headers:{"X-Test":"fixture"}}}));
  const fetcher=vi.fn(async (..._args: any[])=>new Response("{}"));vi.stubGlobal("fetch",fetcher);await c.request("/api/v2/network/stations");
  expect(fetcher.mock.calls[0][0]).toBe("/api/v2/network/stations");expect(fetcher.mock.calls[0][1].headers).toEqual({"X-Test":"fixture"});
 });
});

describe("unified station requests preserve API namespaces", () => {
  it("keeps legacy actions on v1 while station reads and experimental actions use v2", async () => {
    const fetcher = vi
      .fn()
      .mockImplementation(
        async () =>
          new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetcher);
    await request("/api/v2/network/stations?mode=current");
    await post("/api/v2/stations/fixture/training-jobs", { variant: "M0" });
    await post("/models/11110/rollback", { reason: "TEST ONLY" });
    expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
      "/api/v2/network/stations?mode=current",
      "/api/v2/stations/fixture/training-jobs",
      "/api/v1/models/11110/rollback",
    ]);
  });

});

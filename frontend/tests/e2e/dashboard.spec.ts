import { test, expect } from "@playwright/test";
const station=(id:string,name:string,code:string)=>({station_id:id,station_name:name,district_name:name,region_name:"서울특별시",legacy_district_code:code,provider:"seoul",source_kind:"observed",model_ready:false,model_status:"pending",capabilities:{predict:false},observed_date:"2026-09-30",latest_actual_level:-2,level_unit:"GL-m",data_status:"observations_available"});
const stations=[station("seoul:fixture-jongno","종로구","11110"),station("seoul:fixture-jung","중구","11140")];
test.beforeEach(async({page})=>{
 page.on("pageerror",e=>console.log("BROWSER_ERROR",e.message));
 page.on("console",m=>{if(m.type()==="error")console.log("BROWSER_CONSOLE",m.text());});
 await page.route(/^https?:\/\/[^/]+\/api\//,async route=>{
  const url=new URL(route.request().url());let body:unknown={};
  if(url.pathname==="/api/v2/network/stations")body={stations};
  else if(url.pathname.endsWith("/replays"))body={replays:[]};
  else if(url.pathname.endsWith("/history"))body={history:[],rows:[]};
  else if(url.pathname.endsWith("/pipeline"))body={steps:[]};
  else if(url.pathname.includes("rainfall"))body={stations:[],dates:[]};
  await route.fulfill({json:body});
 });
 await page.goto("/dashboard/");await page.keyboard.press("Escape");
});
test("station selection follows the selected district and keeps missing predictions empty",async({page})=>{
 await page.getByRole("navigation").getByRole("button",{name:/관측소 상세/}).click();
 const picker=page.getByLabel("관측소 선택").first();await expect(picker).toContainText("종로구");
 await picker.selectOption("seoul:fixture-jung");await expect(picker).toHaveValue("seoul:fixture-jung");
 await page.getByRole("navigation").getByRole("button",{name:/관측소 상세/}).click();await expect(page.getByRole("heading",{name:/관측소 상세/})).toBeVisible();
 await expect(page.locator("body")).not.toContainText("NaN");await expect(page.locator("body")).not.toContainText("undefined");
});
test("switches data scope without mixing Seoul fixtures into national observations",async({page})=>{
 await page.getByLabel("자료 범위").selectOption("observed");await expect(page.getByLabel("자료 범위")).toHaveValue("observed");
 await expect(page.locator(".service-scope-note")).toContainText("0곳");
 await page.getByLabel("자료 범위").selectOption("simulation");await expect(page.locator(".service-scope-note")).toContainText("현장 실측");
});
test("shows API errors and recovers through refresh",async({page})=>{
 await page.route("**/api/v2/network/stations?**",r=>r.fulfill({status:503,json:{detail:"TEST ONLY unavailable"}}));await page.getByLabel("새로고침").click();await expect(page.locator("body")).toContainText("TEST ONLY unavailable");
 await page.unroute("**/api/v2/network/stations?**");await page.getByLabel("새로고침").click();await page.getByRole("navigation").getByRole("button",{name:/관측소 상세/}).click();await expect(page.getByLabel("관측소 선택").first()).toContainText("종로구");
});
test("keeps mobile navigation and reduced motion controls usable",async({page})=>{
 await page.setViewportSize({width:390,height:844});const reduced=page.getByLabel("동작 줄이기");await reduced.check();await expect(page.locator(".app")).toHaveClass(/reduced/);
 await page.getByRole("button",{name:/모델 관리 · 시연/}).click();await expect(page.getByRole("heading",{name:/모델 관리 · 시연/})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2)).toBe(true);
});

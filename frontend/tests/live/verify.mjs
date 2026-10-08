import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium, expect } from '@playwright/test';
const base=process.argv[2] || 'http://localhost:8100';
const output=process.argv[3] ? path.resolve(process.argv[3]) : path.resolve(import.meta.dirname,'../../../runtime/live-verification');
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try {
 const network=await page.request.get(base+'/api/v2/network/stations?mode=current');expect(network.status()).toBe(200);const payload=await network.json();expect(payload.stations.length).toBeGreaterThanOrEqual(25);
 await page.goto(base+'/dashboard/');await page.keyboard.press('Escape');await expect(page.getByRole('heading',{name:'관측소 현황',exact:true})).toBeVisible();
 await page.waitForTimeout(1500);await page.screenshot({path:output+'/overview.png',fullPage:true});
 await page.getByRole('navigation').getByRole('button',{name:/관측소 상세/}).click();const picker=page.getByLabel('관측소 선택').first();await expect(picker).toBeVisible();
 const jongno=payload.stations.find(s=>s.legacy_district_code==='11110');await picker.selectOption(jongno.station_id);await expect(picker).toHaveValue(jongno.station_id);
 await page.waitForTimeout(1200);await page.screenshot({path:output+'/detail-3d.png',fullPage:true});
 await page.getByLabel('3D 보기').uncheck();await expect(page.locator('body')).not.toContainText('NaN');await page.screenshot({path:output+'/detail-2d.png',fullPage:true});
 const historicalResponse=await page.request.get(base+'/api/v2/network/stations?mode=historical_replay&as_of=2026-07-31');const historical=await historicalResponse.json();const saved=historical.stations.find(s=>s.legacy_district_code==='11110');expect(saved.prediction).not.toBeNull();expect(saved.model_version).toBeTruthy();
 await page.getByLabel('조회 모드').selectOption('historical_replay');await page.getByLabel('입력 기준일').fill('2026-07-31');await page.getByLabel('3D 보기').check();await expect(page.locator('.prediction-card, .station-card').last()).toContainText('2026-08-01');await page.waitForTimeout(1000);await page.screenshot({path:output+'/historical-3d.png',fullPage:true});await page.getByLabel('3D 보기').uncheck();await page.screenshot({path:output+'/historical-2d.png',fullPage:true});
 await page.getByRole('navigation').getByRole('button',{name:/모델 관리/}).click();await expect(page.getByRole('heading',{name:'모델 관리 · 시연',exact:true})).toBeVisible();await page.screenshot({path:output+'/operations.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.getByLabel('동작 줄이기').check();await expect(page.locator('.app')).toHaveClass(/reduced/);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);await page.screenshot({path:output+'/mobile.png',fullPage:true});
 expect(errors).toEqual([]);
 const ready=await page.request.get(base+'/health/ready');const live=await page.request.get(base+'/health/live');
 const report={at:new Date().toISOString(),base_url:base,live:live.status(),ready:ready.status(),station_count:payload.stations.length,seoul_count:payload.stations.filter(s=>s.provider==='seoul').length,page_errors:errors,historical_prediction:{as_of:'2026-07-31',forecast_date:saved.forecast_date,prediction:saved.prediction,model_version:saved.model_version,ready_count:historical.stations.filter(s=>s.provider==='seoul'&&s.model_ready).length},checks:['real API station directory','station selection','3D and 2D detail','operations view','mobile and reduced motion'],scope:'read-only UI/API verification on copied runtime; no new model accuracy claim'};
 await fs.writeFile(output+'/live-ui.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
} finally {await browser.close();}

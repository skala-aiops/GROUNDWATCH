import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
 testDir:"./tests/e2e", fullyParallel:false, retries:0,
 outputDir:"test-results", reporter:[["list"],["html",{open:"never"}]],
 use:{baseURL:process.env.E2E_BASE_URL || "http://127.0.0.1:4173",trace:"retain-on-failure"},
 projects:[{name:"chromium",use:{...devices["Desktop Chrome"],channel:"chrome"}}],
 webServer:process.env.E2E_BASE_URL ? undefined : {command:"npm run dev -- --host 127.0.0.1 --port 4173 --strictPort",url:"http://127.0.0.1:4173/dashboard/",reuseExistingServer:false},
});

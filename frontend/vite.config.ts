import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  server: {
    proxy: {
      "/api": "http://localhost:8100",
      "/health": "http://localhost:8100",
      "/metrics": "http://localhost:8100",
    },
  },
});

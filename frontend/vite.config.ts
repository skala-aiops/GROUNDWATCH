import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  base: "/dashboard/",
  server: {
    proxy: {
      "/api": "http://localhost:8100",
      "/health": "http://localhost:8100",
      "/metrics": "http://localhost:8100",
    },
  },
});

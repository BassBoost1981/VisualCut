/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: Vite auf 5173, alle API-Pfade gehen per Proxy an `visualcut serve` (8765).
const API = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/projects": API,
      "/analyze": API,
      "/jobs": API,
      "/health": API,
      "/ws": { target: API.replace("http", "ws"), ws: true },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});

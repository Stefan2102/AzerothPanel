import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// `npm run dev` proxies the API to a panel started with `python -m backend run`.
const panel = "http://127.0.0.1:8090";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    proxy: {
      "/api": {
        target: panel,
        changeOrigin: true,
        configure: (proxy) => proxy.on("proxyReq", (req) => req.setHeader("origin", panel)),
      },
      "/ws": {
        target: panel,
        ws: true,
        changeOrigin: true,
        configure: (proxy) => proxy.on("proxyReqWs", (req) => req.setHeader("origin", panel)),
      },
    },
  },
});

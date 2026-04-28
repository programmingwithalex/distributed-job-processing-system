import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";


const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";


/** Configure the local frontend dev server and API proxy. */
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (requestPath: string) => requestPath.replace(/^\/api/, ""),
      },
    },
  },
});
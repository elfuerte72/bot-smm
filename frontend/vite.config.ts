import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Vite-конфиг Mini App. Dev — на :5173, прокся /api в backend (:8000).
// Build → ./dist; multi-stage Docker копирует в src/webapp/static.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 200,
    rollupOptions: {
      output: {
        // Имена с хешем — Traefik+Dokploy будут отдавать с долгим Cache-Control,
        // обновления гарантированно невидимы клиенту до нового билда.
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});

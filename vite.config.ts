import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

/** Hosts Vite must accept (Vite 8 blocks unknown Host → blank published UI). */
const ALLOWED_HOSTS = [
  "evolvingcook.grok.me",
  ".grok.me",
  ".grok-sandbox.com",
  "localhost",
  "127.0.0.1",
] as const;

// Preview contract: 0.0.0.0:8080. SPA only — browser talks to API directly.
// Published FE origin: https://evolvingcook.grok.me (CORS allowlisted on API).
export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 8080,
    strictPort: true,
    allowedHosts: [...ALLOWED_HOSTS],
  },
  preview: {
    host: "0.0.0.0",
    port: 8080,
    strictPort: true,
    allowedHosts: [...ALLOWED_HOSTS],
  },
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "src"),
    },
  },
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      injectRegister: null,
      includeAssets: ["fonts/*.woff2", "icons/*.png", "favicon.svg"],
      manifest: {
        name: "Evolving Cook",
        short_name: "Cook",
        description:
          "Kitchen boards, walk sheet, and orders for Hilton London Wembley banqueting.",
        theme_color: "#1f2335",
        background_color: "#1f2335",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        scope: "/",
        icons: [
          {
            src: "/icons/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,svg,woff2,png,webp}"],
        navigateFallback: "/index.html",
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: false,
        runtimeCaching: [
          {
            urlPattern: ({ url }) =>
              url.origin === "https://api.apidiscoverysolution.uk",
            handler: "NetworkOnly",
          },
        ],
      },
      devOptions: {
        enabled: false,
      },
    }),
  ],
});

/**
 * Hard client refresh for published PWA (evolvingcook.grok.me).
 *
 * Plain location.reload() reuses the active service-worker precache, so a
 * contract-skew "Refresh" never picks up a newly deployed bundle.
 * Nuclear path: activate waiting SW if any → unregister → wipe Cache Storage
 * → navigate with a cache-buster so index.html + assets are network-fetched.
 */
export async function forceAppRefresh(): Promise<void> {
  try {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(
        regs.map(async (reg) => {
          try {
            await reg.update();
          } catch {
            /* ignore */
          }
          // vite-plugin-pwa / workbox listens for SKIP_WAITING
          if (reg.waiting) {
            reg.waiting.postMessage({ type: "SKIP_WAITING" });
          }
          // Drop registration so the next load is not pinned to old precache
          try {
            await reg.unregister();
          } catch {
            /* ignore */
          }
        }),
      );
    }

    if (typeof caches !== "undefined") {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
  } catch {
    // Always fall through to navigation
  }

  const u = new URL(window.location.href);
  u.searchParams.set("_ec_r", String(Date.now()));
  // replace — no back-button into a half-dead SW page
  window.location.replace(u.href);
}

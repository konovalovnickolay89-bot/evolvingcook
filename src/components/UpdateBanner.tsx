import { useEffect, useState } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";
import { forceAppRefresh } from "@/lib/forceRefresh";

/**
 * PWA update path — stale cached build against a moved contract is a bad day.
 * registerType: "prompt"; user tap runs skipWaiting + hard cache clear.
 */
export function UpdateBanner() {
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    immediate: true,
    onRegisteredSW(_swUrl, reg) {
      if (!reg) return;
      // Kitchen shift is long — check for a new build every 5 minutes
      const tick = () => {
        void reg.update();
      };
      tick();
      setInterval(tick, 5 * 60 * 1000);
    },
  });

  useEffect(() => {
    if (needRefresh) setShow(true);
  }, [needRefresh]);

  if (!show) return null;

  return (
    <div className="banner banner--update" role="status">
      <span>Update available</span>
      <button
        type="button"
        className="banner__action"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setNeedRefresh(false);
          // Activate waiting worker, then nuclear clear so reload cannot stick
          void (async () => {
            try {
              await updateServiceWorker(true);
            } catch {
              /* forceAppRefresh still runs */
            }
            await forceAppRefresh();
          })();
        }}
      >
        {busy ? "Reloading…" : "Reload"}
      </button>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";

/**
 * PWA update path — stale cached build against a moved contract is a bad day.
 * registerType: "prompt" + visible action; skipWaiting only after Mykola taps.
 */
export function UpdateBanner() {
  const [show, setShow] = useState(false);

  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    immediate: true,
    onRegisteredSW(_swUrl, reg) {
      // Poll for updates periodically while app is open
      if (reg) {
        setInterval(() => {
          void reg.update();
        }, 60 * 60 * 1000);
      }
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
        onClick={() => {
          void updateServiceWorker(true);
          setNeedRefresh(false);
          setShow(false);
        }}
      >
        Reload
      </button>
    </div>
  );
}

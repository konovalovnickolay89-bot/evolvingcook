import { useEffect } from "react";

/** Shrink beyond this (px) while typing = on-screen keyboard, not URL-bar jitter. */
const KEYBOARD_MIN_PX = 120;

function isTyping(): boolean {
  const el = document.activeElement;
  return (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    (el instanceof HTMLElement && el.isContentEditable)
  );
}

/**
 * Chat-style pages: pin the app shell to the *visible* viewport.
 *
 * Mirrors window.visualViewport into --app-vh / --app-vt so a fill-mode
 * shell (`.app-shell--fill`) stays exactly on screen when the phone keyboard
 * opens (iOS pans the visual viewport, Android shrinks it), and flags
 * <html data-keyboard="open"> so the nav can step aside while typing.
 * Clears everything when disabled, so other pages keep normal page scroll.
 */
export function useViewportFill(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    const root = document.documentElement;
    const vv = window.visualViewport;
    if (!vv) return;

    let baseline = 0;
    let baseWidth = 0;

    const clear = () => {
      root.style.removeProperty("--app-vh");
      root.style.removeProperty("--app-vt");
      delete root.dataset.keyboard;
    };

    const sync = () => {
      // Pinch-zoom also shrinks the visual viewport — leave layout alone.
      if (vv.scale > 1.01) {
        clear();
        return;
      }
      if (vv.width !== baseWidth) {
        baseWidth = vv.width; // rotation: re-learn the keyboard-closed height
        baseline = 0;
      }
      baseline = Math.max(baseline, vv.height);
      root.style.setProperty("--app-vh", `${Math.round(vv.height)}px`);
      root.style.setProperty("--app-vt", `${Math.round(vv.offsetTop)}px`);
      if (isTyping() && baseline - vv.height > KEYBOARD_MIN_PX) {
        root.dataset.keyboard = "open";
      } else {
        delete root.dataset.keyboard;
      }
    };

    sync();
    vv.addEventListener("resize", sync);
    vv.addEventListener("scroll", sync);
    window.addEventListener("focusin", sync);
    window.addEventListener("focusout", sync);
    return () => {
      vv.removeEventListener("resize", sync);
      vv.removeEventListener("scroll", sync);
      window.removeEventListener("focusin", sync);
      window.removeEventListener("focusout", sync);
      clear();
    };
  }, [enabled]);
}

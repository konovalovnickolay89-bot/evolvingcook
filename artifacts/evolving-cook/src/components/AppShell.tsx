import type { ReactNode } from "react";
import { VersionBanner } from "./VersionBanner";
import { UpdateBanner } from "./UpdateBanner";
import { getAccessToken } from "@/lib/tokenStorage";

export type AppRoute = "login" | "boards" | "rows" | "walk";

type Props = {
  route: AppRoute;
  onNavigate: (r: AppRoute) => void;
  children: ReactNode;
  /** Hide bottom nav (login) */
  hideNav?: boolean;
};

export function AppShell({ route, onNavigate, children, hideNav }: Props) {
  const token = getAccessToken();
  const tokenHint = token
    ? `${token.slice(0, 6)}…`
    : "no token";

  return (
    <div className="app-shell">
      <div className="app-shell__banners">
        <VersionBanner />
        <UpdateBanner />
      </div>

      <header className="app-header">
        <div className="app-header__brand">
          <p className="app-header__sub">Hilton London Wembley</p>
          <h1 className="app-header__title">Evolving Cook</h1>
        </div>
        <span className="session-chip" title="Auth token present in localStorage">
          {tokenHint}
        </span>
      </header>

      <main className="app-main">{children}</main>

      {!hideNav && (
        <nav className="app-nav" aria-label="Primary">
          <button
            type="button"
            className="app-nav__btn"
            aria-current={route === "boards" ? "page" : undefined}
            onClick={() => onNavigate("boards")}
          >
            Boards
          </button>
          <button
            type="button"
            className="app-nav__btn"
            aria-current={route === "rows" ? "page" : undefined}
            onClick={() => onNavigate("rows")}
          >
            Rows
          </button>
          <button
            type="button"
            className="app-nav__btn"
            aria-current={route === "walk" ? "page" : undefined}
            disabled
            title="Phase 2"
          >
            Walk
          </button>
        </nav>
      )}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <div className="spinner" aria-hidden />
      <p className="state-panel__body">{label}</p>
    </div>
  );
}

export function EmptyState({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div className="state-panel">
      <h2 className="state-panel__title">{title}</h2>
      <p className="state-panel__body">{body}</p>
    </div>
  );
}

import type { ReactNode } from "react";
import { VersionBanner } from "./VersionBanner";
import { UpdateBanner } from "./UpdateBanner";
import { getAccessToken } from "@/lib/tokenStorage";

/** Bottom nav: Boards · Walk · Orders (map). board is nested under Boards. */
export type AppRoute = "login" | "boards" | "board" | "walk" | "orders";

type Props = {
  route: AppRoute;
  onNavigate: (r: AppRoute) => void;
  children: ReactNode;
  hideNav?: boolean;
  /** Tap session chip to re-auth (clears token only). */
  onOpenLogin?: () => void;
};

export function AppShell({
  route,
  onNavigate,
  children,
  hideNav,
  onOpenLogin,
}: Props) {
  const token = getAccessToken();
  const tokenHint = token ? `${token.slice(0, 6)}…` : "no token";

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
        {onOpenLogin ? (
          <button
            type="button"
            className="session-chip session-chip--btn"
            title="Sign in / switch account"
            onClick={onOpenLogin}
          >
            {tokenHint}
          </button>
        ) : (
          <span
            className="session-chip"
            title="Auth token present in localStorage"
          >
            {tokenHint}
          </span>
        )}
      </header>

      <main className="app-main">{children}</main>

      {!hideNav && (
        <nav className="app-nav" aria-label="Primary">
          <button
            type="button"
            className="app-nav__btn"
            aria-current={
              route === "boards" || route === "board" ? "page" : undefined
            }
            onClick={() => onNavigate("boards")}
          >
            Boards
          </button>
          <button
            type="button"
            className="app-nav__btn"
            aria-current={route === "walk" ? "page" : undefined}
            onClick={() => onNavigate("walk")}
          >
            Walk
          </button>
          <button
            type="button"
            className="app-nav__btn"
            aria-current={route === "orders" ? "page" : undefined}
            onClick={() => onNavigate("orders")}
          >
            Orders
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
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-panel">
      <h2 className="state-panel__title">{title}</h2>
      <p className="state-panel__body">{body}</p>
      {action}
    </div>
  );
}

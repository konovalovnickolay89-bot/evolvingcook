import { useCallback, useEffect, useState } from "react";
import { AppShell, type AppRoute } from "@/components/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { BoardsPage } from "@/pages/BoardsPage";
import { RowsDemoPage } from "@/pages/RowsDemoPage";
import { isTokenPresent } from "@/lib/tokenStorage";
import { ensureDbOpen } from "@/db";

function routeFromHash(): AppRoute {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "login") return "login";
  if (h === "rows") return "rows";
  if (h === "walk") return "walk";
  if (h === "boards" || h === "") return "boards";
  return "boards";
}

export function App() {
  const [authed, setAuthed] = useState(() => isTokenPresent());
  const [route, setRoute] = useState<AppRoute>(() =>
    isTokenPresent() ? routeFromHash() : "login",
  );

  useEffect(() => {
    void ensureDbOpen();
  }, []);

  useEffect(() => {
    const onHash = () => {
      if (!isTokenPresent()) {
        setRoute("login");
        return;
      }
      setRoute(routeFromHash());
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Token eviction (iOS) — detect when localStorage token vanishes without
  // wiping Dexie. Re-auth path only.
  useEffect(() => {
    const id = window.setInterval(() => {
      const has = isTokenPresent();
      setAuthed((prev) => {
        if (prev && !has) {
          setRoute("login");
          return false;
        }
        return has;
      });
    }, 4000);
    return () => window.clearInterval(id);
  }, []);

  const navigate = useCallback((r: AppRoute) => {
    if (r === "login") {
      window.location.hash = "#/login";
      setRoute("login");
      return;
    }
    window.location.hash = `#/${r}`;
    setRoute(r);
  }, []);

  const onLoginSuccess = useCallback(() => {
    setAuthed(true);
    window.location.hash = "#/rows";
    setRoute("rows");
  }, []);

  if (!authed || route === "login") {
    return (
      <AppShell route="login" onNavigate={navigate} hideNav>
        <LoginPage onSuccess={onLoginSuccess} />
      </AppShell>
    );
  }

  return (
    <AppShell route={route} onNavigate={navigate}>
      {route === "rows" ? <RowsDemoPage /> : <BoardsPage />}
    </AppShell>
  );
}

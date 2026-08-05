import { useCallback, useEffect, useState } from "react";
import { AppShell, type AppRoute } from "@/components/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { BoardsPage } from "@/pages/BoardsPage";
import { BoardPage } from "@/pages/BoardPage";
import { WalkPage } from "@/pages/WalkPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { DeliveryPage } from "@/pages/DeliveryPage";
import { InboxPage } from "@/pages/InboxPage";
import { clearAccessToken, isTokenPresent } from "@/lib/tokenStorage";
import { ensureDbOpen } from "@/db";

type BoardTarget = { serviceDate: string; section: string } | null;

type Route = AppRoute | "delivery" | "inbox";

function routeFromHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "login") return "login";
  if (h === "walk") return "walk";
  if (h === "inbox") return "inbox";
  if (h.startsWith("delivery/")) return "delivery";
  if (h === "orders" || h.startsWith("orders")) return "orders";
  if (h.startsWith("board/")) return "board";
  if (h === "boards" || h === "") return "boards";
  return "boards";
}

function boardFromHash(): BoardTarget {
  const h = window.location.hash.replace(/^#\/?/, "");
  const m = /^board\/(\d{4}-\d{2}-\d{2})\/([a-z0-9_]+)$/i.exec(h);
  if (!m) return null;
  return { serviceDate: m[1]!, section: m[2]! };
}

function poIdsFromHash(): number[] {
  const h = window.location.hash.replace(/^#\/?/, "");
  const m = /^orders\/([\d,]+)$/.exec(h);
  if (!m) return [];
  return m[1]!
    .split(",")
    .map(Number)
    .filter((n) => n > 0);
}

function deliveryIdFromHash(): number | null {
  const h = window.location.hash.replace(/^#\/?/, "");
  const m = /^delivery\/(\d+)$/.exec(h);
  if (!m) return null;
  return Number(m[1]);
}

/** Auth-only — never clears Dexie / walk data. */
function openLoginScreen(): void {
  clearAccessToken();
  window.location.hash = "#/login";
}

export function App() {
  const [authed, setAuthed] = useState(() => isTokenPresent());
  const [route, setRoute] = useState<Route>(() =>
    isTokenPresent() ? routeFromHash() : "login",
  );
  const [boardTarget, setBoardTarget] = useState<BoardTarget>(() =>
    isTokenPresent() ? boardFromHash() : null,
  );
  const [poIds, setPoIds] = useState<number[]>(() =>
    isTokenPresent() ? poIdsFromHash() : [],
  );
  const [deliveryId, setDeliveryId] = useState<number | null>(() =>
    isTokenPresent() ? deliveryIdFromHash() : null,
  );

  useEffect(() => {
    void ensureDbOpen();
  }, []);

  useEffect(() => {
    // No token → login is the published entry surface
    if (!isTokenPresent()) {
      setAuthed(false);
      setRoute("login");
      if (!window.location.hash || window.location.hash === "#/" || window.location.hash === "#") {
        window.location.hash = "#/login";
      }
    }
  }, []);

  useEffect(() => {
    const onHash = () => {
      const r = routeFromHash();
      if (r === "login" || !isTokenPresent()) {
        if (r === "login") clearAccessToken();
        setAuthed(false);
        setRoute("login");
        setBoardTarget(null);
        return;
      }
      setAuthed(true);
      setRoute(r);
      setBoardTarget(r === "board" ? boardFromHash() : null);
      if (r === "orders") setPoIds(poIdsFromHash());
      if (r === "delivery") setDeliveryId(deliveryIdFromHash());
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      const has = isTokenPresent();
      setAuthed((prev) => {
        if (prev && !has) {
          setRoute("login");
          setBoardTarget(null);
          return false;
        }
        return has;
      });
    }, 4000);
    return () => window.clearInterval(id);
  }, []);

  const navigate = useCallback((r: AppRoute) => {
    if (r === "login") {
      openLoginScreen();
      setAuthed(false);
      setRoute("login");
      setBoardTarget(null);
      return;
    }
    if (r === "board") return;
    window.location.hash = `#/${r}`;
    setRoute(r);
    setBoardTarget(null);
    setDeliveryId(null);
  }, []);

  const openSection = useCallback((serviceDate: string, section: string) => {
    window.location.hash = `#/board/${serviceDate}/${section}`;
    setBoardTarget({ serviceDate, section });
    setRoute("board");
  }, []);

  const openOrders = useCallback((ids: number[]) => {
    setPoIds(ids);
    window.location.hash = `#/orders/${ids.join(",")}`;
    setRoute("orders");
  }, []);

  const openDelivery = useCallback((id: number) => {
    setDeliveryId(id);
    window.location.hash = `#/delivery/${id}`;
    setRoute("delivery");
  }, []);

  const openInbox = useCallback(() => {
    window.location.hash = "#/inbox";
    setRoute("inbox");
  }, []);

  const onLoginSuccess = useCallback(() => {
    setAuthed(true);
    window.location.hash = "#/boards";
    setRoute("boards");
  }, []);

  const onOpenLogin = useCallback(() => {
    openLoginScreen();
    setAuthed(false);
    setRoute("login");
    setBoardTarget(null);
  }, []);

  if (!authed || route === "login") {
    return (
      <AppShell
        route="login"
        onNavigate={navigate}
        hideNav
        onOpenLogin={onOpenLogin}
      >
        <LoginPage onSuccess={onLoginSuccess} />
      </AppShell>
    );
  }

  let body: React.ReactNode;
  if (route === "walk") {
    body = <WalkPage onOpenOrders={openOrders} />;
  } else if (route === "inbox") {
    body = <InboxPage onBack={() => navigate("boards")} />;
  } else if (route === "delivery" && deliveryId) {
    body = (
      <DeliveryPage
        deliveryId={deliveryId}
        onBack={() => navigate("orders")}
      />
    );
  } else if (route === "orders") {
    body = (
      <OrdersPage initialPoIds={poIds} onOpenDelivery={openDelivery} />
    );
  } else if (route === "board" && boardTarget) {
    body = (
      <BoardPage
        serviceDate={boardTarget.serviceDate}
        section={boardTarget.section}
        onBack={() => navigate("boards")}
      />
    );
  } else {
    body = (
      <BoardsPage onOpenSection={openSection} onOpenInbox={openInbox} />
    );
  }

  const shellRoute: AppRoute =
    route === "board" || route === "inbox"
      ? "boards"
      : route === "delivery"
        ? "orders"
        : route;

  return (
    <AppShell
      route={shellRoute}
      onNavigate={navigate}
      onOpenLogin={onOpenLogin}
    >
      {body}
    </AppShell>
  );
}

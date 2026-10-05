import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AppShell, type AppRoute } from "@/components/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { BoardsPage } from "@/pages/BoardsPage";
import { BoardPage } from "@/pages/BoardPage";
import { StationLogPage } from "@/pages/StationLogPage";
import { WalkPage } from "@/pages/WalkPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { DeliveryPage } from "@/pages/DeliveryPage";
import { InboxPage } from "@/pages/InboxPage";
import { clearAccessToken, isTokenPresent } from "@/lib/tokenStorage";
import { readStationContext, rememberStation } from "@/lib/stationContext";
import { ensureDbOpen } from "@/db";

type StationTarget = { serviceDate: string; section: string } | null;

type Route = AppRoute | "delivery" | "inbox" | "station-log";

function routeFromHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "login") return "login";
  if (h === "walk") return "walk";
  if (h === "inbox") return "inbox";
  if (h.startsWith("delivery/")) return "delivery";
  if (h === "orders" || h.startsWith("orders")) return "orders";
  if (h.startsWith("station/")) return "station-log";
  if (h.startsWith("board/")) return "board";
  if (h === "boards" || h === "") return "boards";
  return "boards";
}

function boardFromHash(): StationTarget {
  const h = window.location.hash.replace(/^#\/?/, "");
  const m = /^board\/(\d{4}-\d{2}-\d{2})\/([a-z0-9_]+)$/i.exec(h);
  if (!m) return null;
  return { serviceDate: m[1]!, section: m[2]! };
}

function stationLogFromHash(): StationTarget {
  const h = window.location.hash.replace(/^#\/?/, "");
  const m = /^station\/(\d{4}-\d{2}-\d{2})\/([a-z0-9_]+)\/log$/i.exec(h);
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

function stationFromRoute(r: Route): StationTarget {
  if (r === "board") return boardFromHash();
  if (r === "station-log") return stationLogFromHash();
  return null;
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
  const [station, setStation] = useState<StationTarget>(() =>
    isTokenPresent() ? stationFromRoute(routeFromHash()) : null,
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
    if (!isTokenPresent()) {
      setAuthed(false);
      setRoute("login");
      if (
        !window.location.hash ||
        window.location.hash === "#/" ||
        window.location.hash === "#"
      ) {
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
        setStation(null);
        return;
      }
      setAuthed(true);
      setRoute(r);
      const target = stationFromRoute(r);
      setStation(target);
      if (target) rememberStation(target.serviceDate, target.section);
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
          setStation(null);
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
      setStation(null);
      return;
    }
    if (r === "board") return;
    window.location.hash = `#/${r}`;
    setRoute(r);
    setStation(null);
    setDeliveryId(null);
  }, []);

  const openStationLog = useCallback((serviceDate: string, section: string) => {
    rememberStation(serviceDate, section);
    window.location.hash = `#/station/${serviceDate}/${section}/log`;
    setStation({ serviceDate, section });
    setRoute("station-log");
  }, []);

  const openBoard = useCallback((serviceDate: string, section: string) => {
    rememberStation(serviceDate, section);
    window.location.hash = `#/board/${serviceDate}/${section}`;
    setStation({ serviceDate, section });
    setRoute("board");
  }, []);

  /**
   * Bottom-nav only. "Station" returns to the station you were on (board,
   * with your last face) when tapped from Walk / Orders / elsewhere; tapped
   * again on a station surface it opens the picker to switch station.
   */
  const navFromShell = useCallback(
    (r: AppRoute) => {
      if (r === "boards") {
        const onStationSurface =
          route === "boards" || route === "board" || route === "station-log";
        if (!onStationSurface) {
          const ctx = readStationContext();
          if (ctx) {
            openBoard(ctx.serviceDate, ctx.section);
            return;
          }
        }
      }
      navigate(r);
    },
    [route, navigate, openBoard],
  );

  const openWalk = useCallback(() => {
    window.location.hash = "#/walk";
    setRoute("walk");
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

  const onLoginSuccess = useCallback(() => {
    setAuthed(true);
    window.location.hash = "#/boards";
    setRoute("boards");
  }, []);

  const onOpenLogin = useCallback(() => {
    openLoginScreen();
    setAuthed(false);
    setRoute("login");
    setStation(null);
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

  let body: ReactNode;
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
  } else if (route === "station-log" && station) {
    body = (
      <StationLogPage
        key={`${station.serviceDate}:${station.section}`}
        serviceDate={station.serviceDate}
        section={station.section}
        onBack={() => navigate("boards")}
        onContinue={() => openBoard(station.serviceDate, station.section)}
        onOpenWalk={openWalk}
      />
    );
  } else if (route === "board" && station) {
    body = (
      <BoardPage
        key={`${station.serviceDate}:${station.section}`}
        serviceDate={station.serviceDate}
        section={station.section}
        onBack={() => openStationLog(station.serviceDate, station.section)}
        onOpenWalk={openWalk}
      />
    );
  } else {
    body = (
      <BoardsPage onOpenStation={openStationLog} onResumeBoard={openBoard} />
    );
  }

  const shellRoute: AppRoute =
    route === "board" || route === "inbox" || route === "station-log"
      ? "boards"
      : route === "delivery"
        ? "orders"
        : route;

  return (
    <AppShell
      route={shellRoute}
      onNavigate={navFromShell}
      onOpenLogin={onOpenLogin}
    >
      {body}
    </AppShell>
  );
}

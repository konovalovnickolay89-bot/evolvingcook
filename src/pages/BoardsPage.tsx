import { useMemo, useState } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { getBoard, getDay, openDay } from "@/api/boards";
import { listProposals } from "@/api/assist";
import { ApiError } from "@/api/client";
import {
  ALL_SECTIONS,
  SECTION_LABELS,
  SECTION_SERVICE_MODE,
  type SectionId,
} from "@/contract";
import { todayServiceDate, yesterdayServiceDate } from "@/lib/dates";
import { isEightySix } from "@/lib/lineDisplay";
import { EmptyState, LoadingState } from "@/components/AppShell";

type Props = {
  onOpenSection: (serviceDate: string, section: string) => void;
  onOpenInbox: () => void;
};

type DayPick = "today" | "yesterday";

export function BoardsPage({ onOpenSection, onOpenInbox }: Props) {
  const [pick, setPick] = useState<DayPick>("today");
  const serviceDate =
    pick === "today" ? todayServiceDate() : yesterdayServiceDate();
  const qc = useQueryClient();

  const dayQ = useQuery({
    queryKey: ["day", serviceDate],
    queryFn: ({ signal }) => getDay(serviceDate, signal),
    retry: false,
  });

  const pendingQ = useQuery({
    queryKey: ["proposals", "pending-count"],
    queryFn: ({ signal }) =>
      listProposals({ status: "pending", limit: 50 }, signal),
    retry: false,
    refetchInterval: 15000,
  });

  const openMut = useMutation({
    mutationFn: () =>
      openDay({
        service_date: serviceDate,
        sections: [...ALL_SECTIONS],
        generate_lines: true,
        notes: "",
      }),
    onSuccess: (data) => {
      qc.setQueryData(["day", serviceDate], data);
    },
  });

  const dayMissing =
    dayQ.isError &&
    dayQ.error instanceof ApiError &&
    dayQ.error.status === 404;

  const dayAuthError =
    dayQ.isError &&
    dayQ.error instanceof ApiError &&
    dayQ.error.status === 401;

  const dayOtherError = dayQ.isError && !dayMissing && !dayAuthError;
  const day = dayQ.data;

  const sectionMap = useMemo(
    () => new Map((day?.sections ?? []).map((s) => [s.section, s])),
    [day?.sections],
  );

  // Day payload has line_count only — hydrate done/left/86 from section boards
  // for active sections (map §2). Empty sections skip the extra fetch.
  const activeSections = useMemo(
    () =>
      ALL_SECTIONS.filter((id) => {
        const s = sectionMap.get(id);
        return s && (s.line_count ?? 0) > 0;
      }),
    [sectionMap],
  );

  const boardStatsQ = useQueries({
    queries: activeSections.map((section) => ({
      queryKey: ["board-stats", serviceDate, section],
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        getBoard(serviceDate, section, signal),
      enabled: Boolean(day),
      staleTime: 30_000,
      retry: false,
    })),
  });

  const statsBySection = useMemo(() => {
    const map = new Map<
      string,
      { done: number; left: number; eightySix: number; total: number }
    >();
    activeSections.forEach((section, i) => {
      const board = boardStatsQ[i]?.data;
      if (!board) return;
      let done = 0;
      let eightySix = 0;
      for (const l of board.lines) {
        if (isEightySix(l.status)) eightySix += 1;
        else if (l.ticked) done += 1;
      }
      const total = board.line_count;
      map.set(section, {
        done,
        eightySix,
        total,
        left: Math.max(0, total - done - eightySix),
      });
    });
    return map;
  }, [activeSections, boardStatsQ]);

  const pendingCount = pendingQ.data?.length ?? 0;
  const assistOffline =
    pendingQ.isError &&
    pendingQ.error instanceof Error &&
    /A2A|unreachable|Failed to fetch|Network/i.test(pendingQ.error.message);

  return (
    <div className="stack">
      <div className="day-home__header">
        <div className="day-home__title-row">
          <div>
            <h2 className="page-title">Day home</h2>
            <p className="page-lead" style={{ marginBottom: 0 }}>
              Open day, then boards. No covers. Yesterday only one step back.
            </p>
          </div>
          <button
            type="button"
            className="inbox-btn"
            onClick={onOpenInbox}
            aria-label={
              pendingCount
                ? `Proposals inbox, ${pendingCount} pending`
                : "Proposals inbox"
            }
          >
            <span className="board-row__badge board-row__badge--assist">A</span>
            {pendingCount > 0 ? (
              <span className="inbox-btn__count">{pendingCount}</span>
            ) : null}
          </button>
        </div>
        {assistOffline ? (
          <p className="board-row__meta" style={{ color: "var(--comment)" }}>
            assist offline
          </p>
        ) : null}
      </div>

      <div className="face-toggle" role="tablist" aria-label="Service day">
        <button
          type="button"
          role="tab"
          aria-selected={pick === "today"}
          className={`face-toggle__btn${pick === "today" ? " is-on" : ""}`}
          onClick={() => setPick("today")}
        >
          Today
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pick === "yesterday"}
          className={`face-toggle__btn${pick === "yesterday" ? " is-on" : ""}`}
          onClick={() => setPick("yesterday")}
        >
          Yesterday
        </button>
      </div>

      <div className="day-chip-row">
        <span className="num num--planned">{serviceDate}</span>
        {day ? (
          <span
            className={`status-chip status-chip--${day.status === "open" ? "ok" : "muted"}`}
          >
            {day.status}
          </span>
        ) : dayMissing ? (
          <span className="status-chip status-chip--muted">not open</span>
        ) : dayQ.isLoading ? (
          <span className="status-chip status-chip--muted">…</span>
        ) : null}
      </div>

      {dayQ.isLoading ? <LoadingState label="Loading day…" /> : null}

      {dayAuthError ? (
        <EmptyState
          title="Sign in required"
          body="Session missing or expired. Sign in again — local data is kept."
        />
      ) : null}

      {dayOtherError ? (
        <EmptyState
          title="Could not load day"
          body={
            dayQ.error instanceof Error ? dayQ.error.message : "Request failed"
          }
        />
      ) : null}

      {dayMissing && !dayQ.isLoading ? (
        <div className="stack">
          <EmptyState
            title="Day not open"
            body="One tap opens the service day. Partial catalogue is normal — empty sections get quick-add."
          />
          <button
            type="button"
            className="btn btn--primary btn--block"
            disabled={openMut.isPending}
            onClick={() => openMut.mutate()}
          >
            {openMut.isPending ? "Opening…" : "Open day"}
          </button>
          {openMut.isError ? (
            <p className="field__error">
              {openMut.error instanceof Error
                ? openMut.error.message
                : "Open failed"}
            </p>
          ) : null}
        </div>
      ) : null}

      {day ? (
        <div className="section-cards" role="list">
          {ALL_SECTIONS.map((id) => {
            const sec = sectionMap.get(id);
            const lines = sec?.line_count ?? 0;
            const stats = statsBySection.get(id);
            const mode = SECTION_SERVICE_MODE[id as SectionId];
            const badgeClass =
              mode === "check"
                ? "check"
                : mode === "replenish"
                  ? "replenish"
                  : "produce";
            const badgeGlyph =
              mode === "check" ? "C" : mode === "replenish" ? "R" : "P";
            return (
              <button
                key={id}
                type="button"
                className="section-card"
                role="listitem"
                onClick={() => onOpenSection(serviceDate, id)}
              >
                <div className="section-card__top">
                  <span
                    className={`board-row__badge board-row__badge--${badgeClass}`}
                  >
                    {badgeGlyph}
                  </span>
                  <span className="section-card__name">
                    {SECTION_LABELS[id as SectionId]}
                  </span>
                </div>
                <div className="section-card__stats">
                  <div className="section-card__stat">
                    <span className="num num--actual">
                      {stats ? stats.done : lines === 0 ? 0 : "—"}
                    </span>
                    <span className="section-card__stat-label">done</span>
                  </div>
                  <div className="section-card__stat">
                    <span className="num num--planned">
                      {stats ? stats.left : lines === 0 ? 0 : "—"}
                    </span>
                    <span className="section-card__stat-label">left</span>
                  </div>
                  <div className="section-card__stat">
                    <span className="num num--diverged">
                      {stats ? stats.eightySix : lines === 0 ? 0 : "—"}
                    </span>
                    <span className="section-card__stat-label">86</span>
                  </div>
                  <div className="section-card__stat">
                    <span className="num num--proposed">{lines}</span>
                    <span className="section-card__stat-label">lines</span>
                  </div>
                </div>
                <span className="section-card__meta">
                  {sec
                    ? sec.active
                      ? "active"
                      : "inactive"
                    : "not generated yet"}
                  {lines === 0 ? " · empty ok" : ""}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

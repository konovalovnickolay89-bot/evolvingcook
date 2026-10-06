import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getDay, openDay } from "@/api/boards";
import { getDailyBrief } from "@/api/companion";
import { ApiError } from "@/api/client";
import {
  ALL_SECTIONS,
  LAST_STATION_KEY,
  SECTION_LABELS,
  SECTION_PURPOSE,
  type SectionId,
} from "@/contract";
import { todayServiceDate, yesterdayServiceDate } from "@/lib/dates";
import { readStationContext } from "@/lib/stationContext";
import { EmptyState, LoadingState } from "@/components/AppShell";

type Props = {
  onOpenStation: (serviceDate: string, section: string) => void;
  /** Resume card: straight back to the board, skipping the log screen. */
  onResumeBoard: (serviceDate: string, section: string) => void;
  onOpenChat: () => void;
};

type DayPick = "today" | "yesterday";

function readLastStation(): SectionId | null {
  try {
    const v = localStorage.getItem(LAST_STATION_KEY);
    if (v && (ALL_SECTIONS as readonly string[]).includes(v)) {
      return v as SectionId;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function BoardsPage({ onOpenStation, onResumeBoard, onOpenChat }: Props) {
  const resume = useMemo(() => readStationContext(), []);
  const [pick, setPick] = useState<DayPick>(() =>
    resume?.serviceDate === yesterdayServiceDate() ? "yesterday" : "today",
  );
  const serviceDate =
    pick === "today" ? todayServiceDate() : yesterdayServiceDate();
  const qc = useQueryClient();
  const lastStation = useMemo(() => readLastStation(), [serviceDate]);

  const dayQ = useQuery({
    queryKey: ["day", serviceDate],
    queryFn: ({ signal }) => getDay(serviceDate, signal),
    retry: false,
  });

  /* D16 daily brief — cached server-side per date; quiet when offline. */
  const briefQ = useQuery({
    queryKey: ["daily-brief", serviceDate],
    queryFn: ({ signal }) => getDailyBrief(serviceDate, false, signal),
    retry: false,
    staleTime: 10 * 60_000,
  });
  const [briefBusy, setBriefBusy] = useState(false);
  async function refreshBrief() {
    setBriefBusy(true);
    try {
      const fresh = await getDailyBrief(serviceDate, true);
      qc.setQueryData(["daily-brief", serviceDate], fresh);
    } catch {
      /* keep what we have; the card stays */
    } finally {
      setBriefBusy(false);
    }
  }

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

  return (
    <div className="stack">
      <div>
        <h2 className="page-title">Choose station</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Pick your station. Last one is marked — you still choose. Then the
          log, then the board.
        </p>
      </div>

      {resume ? (
        <button
          type="button"
          className="resume-card"
          onClick={() => onResumeBoard(resume.serviceDate, resume.section)}
        >
          <span className="resume-card__kicker">Carry on</span>
          <span className="resume-card__title">
            {SECTION_LABELS[resume.section]} ·{" "}
            {resume.serviceDate === todayServiceDate() ? "Today" : "Yesterday"}
          </span>
          <span className="resume-card__sub">
            Straight back to the {resume.face === "service" ? "service" : "prep"}{" "}
            board — or pick a station below.
          </span>
        </button>
      ) : null}

      <div className="brief-card">
        <div className="brief-card__head">
          <span className="order-assist__badge" aria-hidden>
            ✦
          </span>
          <h3 className="brief-card__title">Today's brief</h3>
          <button
            type="button"
            className="link-back brief-card__refresh"
            disabled={briefBusy}
            onClick={() => void refreshBrief()}
          >
            {briefBusy ? "…" : "Refresh"}
          </button>
        </div>
        {briefQ.data?.tips?.length ? (
          <ul className="brief-card__tips">
            {briefQ.data.tips.map((t, i) => (
              <li key={`${i}-${t.title}`} className="brief-card__tip">
                {t.title ? (
                  <span className="brief-card__tip-title">{t.title}</span>
                ) : null}
                <span className="brief-card__tip-body">{t.body}</span>
              </li>
            ))}
          </ul>
        ) : briefQ.isLoading || briefBusy ? (
          <p className="board-row__meta">Reading the day…</p>
        ) : (
          <p className="board-row__meta">
            Companion offline — tips come back when the kitchen brain is
            connected.
          </p>
        )}
        <button
          type="button"
          className="btn btn--ghost btn--block"
          onClick={onOpenChat}
        >
          Ask the companion
        </button>
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
            body="One tap opens the service day. Then pick a station."
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
            const isLast = lastStation === id;
            return (
              <button
                key={id}
                type="button"
                className={`section-card${isLast ? " is-last" : ""}`}
                role="listitem"
                onClick={() => onOpenStation(serviceDate, id)}
              >
                <div className="section-card__top">
                  <span className="section-card__name">
                    {SECTION_LABELS[id as SectionId]}
                  </span>
                  {isLast ? (
                    <span className="status-chip status-chip--ok">last</span>
                  ) : null}
                </div>
                <span className="section-card__purpose">
                  {SECTION_PURPOSE[id as SectionId]}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

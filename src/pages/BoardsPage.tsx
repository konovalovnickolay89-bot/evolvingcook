import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getDay, openDay } from "@/api/boards";
import { ApiError } from "@/api/client";
import {
  ALL_SECTIONS,
  LAST_STATION_KEY,
  SECTION_LABELS,
  SECTION_PURPOSE,
  type SectionId,
} from "@/contract";
import { todayServiceDate, yesterdayServiceDate } from "@/lib/dates";
import { EmptyState, LoadingState } from "@/components/AppShell";

type Props = {
  onOpenStation: (serviceDate: string, section: string) => void;
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

export function BoardsPage({ onOpenStation }: Props) {
  const [pick, setPick] = useState<DayPick>("today");
  const serviceDate =
    pick === "today" ? todayServiceDate() : yesterdayServiceDate();
  const qc = useQueryClient();
  const lastStation = useMemo(() => readLastStation(), [serviceDate]);

  const dayQ = useQuery({
    queryKey: ["day", serviceDate],
    queryFn: ({ signal }) => getDay(serviceDate, signal),
    retry: false,
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

  return (
    <div className="stack">
      <div>
        <h2 className="page-title">Choose station</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Pick your station. Last one is marked — you still choose. Then the
          log, then the board.
        </p>
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

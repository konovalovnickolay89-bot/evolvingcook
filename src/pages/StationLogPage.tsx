import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getDay, openDay, openSection } from "@/api/boards";
import { ApiError } from "@/api/client";
import { StationLogPanel } from "@/components/StationLogPanel";
import { EmptyState, LoadingState } from "@/components/AppShell";
import {
  ALL_SECTIONS,
  LAST_STATION_KEY,
  SECTION_LABELS,
  SECTION_PURPOSE,
  type SectionId,
} from "@/contract";

type Props = {
  serviceDate: string;
  section: string;
  onBack: () => void;
  onContinue: () => void;
  onOpenWalk: () => void;
};

export function StationLogPage({
  serviceDate,
  section,
  onBack,
  onContinue,
  onOpenWalk,
}: Props) {
  const qc = useQueryClient();
  const [bootError, setBootError] = useState<string | null>(null);
  const title =
    SECTION_LABELS[section as SectionId] ?? section.replace(/_/g, " ");
  const purpose = SECTION_PURPOSE[section as SectionId] ?? "";

  useEffect(() => {
    try {
      if ((ALL_SECTIONS as readonly string[]).includes(section)) {
        localStorage.setItem(LAST_STATION_KEY, section);
      }
    } catch {
      /* ignore */
    }
  }, [section]);

  const dayQ = useQuery({
    queryKey: ["day", serviceDate],
    queryFn: ({ signal }) => getDay(serviceDate, signal),
    retry: false,
  });

  const openDayMut = useMutation({
    mutationFn: () =>
      openDay({
        service_date: serviceDate,
        sections: [...ALL_SECTIONS],
        generate_lines: true,
        notes: "",
      }),
    onSuccess: async (data) => {
      qc.setQueryData(["day", serviceDate], data);
      setBootError(null);
      try {
        await openSection(serviceDate, section, { generate_lines: true });
        await qc.invalidateQueries({
          queryKey: ["station-log", serviceDate, section],
        });
      } catch (e) {
        setBootError(e instanceof Error ? e.message : "Could not open section");
      }
    },
    onError: (e) => {
      setBootError(e instanceof Error ? e.message : "Open day failed");
    },
  });

  const ensuredKey = useRef("");
  useEffect(() => {
    if (!dayQ.data) return;
    const token = `${serviceDate}:${section}`;
    if (ensuredKey.current === token) return;
    ensuredKey.current = token;
    void openSection(serviceDate, section, { generate_lines: false })
      .then(() =>
        qc.invalidateQueries({
          queryKey: ["station-log", serviceDate, section],
        }),
      )
      .catch((e: unknown) => {
        setBootError(
          e instanceof Error ? e.message : "Could not open section",
        );
      });
  }, [dayQ.data, serviceDate, section, qc]);

  const dayMissing =
    dayQ.isError &&
    dayQ.error instanceof ApiError &&
    dayQ.error.status === 404;

  return (
    <div className="stack">
      <button type="button" className="link-back" onClick={onBack}>
        ← Choose station
      </button>
      <div>
        <h2 className="page-title">{title}</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          {serviceDate}
          {purpose ? ` · ${purpose}` : ""}
        </p>
      </div>

      {dayQ.isLoading ? <LoadingState label="Opening station…" /> : null}

      {dayMissing ? (
        <EmptyState
          title="Day not open"
          body="Open today first so the log can carry yesterday’s leftovers and link to the board."
          action={
            <button
              type="button"
              className="btn btn--primary btn--block"
              disabled={openDayMut.isPending}
              onClick={() => openDayMut.mutate()}
            >
              {openDayMut.isPending ? "Opening…" : "Open day"}
            </button>
          }
        />
      ) : null}

      {bootError ? <p className="field__error">{bootError}</p> : null}

      {dayQ.data ? (
        <>
          <StationLogPanel
            serviceDate={serviceDate}
            section={section}
            onOpenWalk={onOpenWalk}
          />
          <button
            type="button"
            className="btn btn--primary btn--block"
            onClick={onContinue}
          >
            Continue to board
          </button>
        </>
      ) : null}
    </div>
  );
}

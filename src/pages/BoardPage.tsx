import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getBoard,
  openSection,
  patchSectionCovers,
  quickAddLine,
  scaleProduce,
  setLineNotes,
  tickComponent,
  tickLine,
  untickComponent,
  untickLine,
} from "@/api/boards";
import { patchSectionSettings } from "@/api/sections";
import { ApiError } from "@/api/client";
import type { ProductionLineOut } from "@/api/types";
import { BoardLine } from "@/components/BoardLine";
import { ModePill, ModePrompt } from "@/components/ModePrompt";
import { StationLogPanel } from "@/components/StationLogPanel";
import { EmptyState, LoadingState } from "@/components/AppShell";
import {
  defaultQuickAddMode,
  SECTION_LABELS,
  type SectionId,
  type SectionMode,
} from "@/contract";
import { isEightySix } from "@/lib/lineDisplay";
import { readStationContext, rememberFace } from "@/lib/stationContext";

export type BoardFace = "mep" | "service";

type Props = {
  serviceDate: string;
  section: string;
  onBack: () => void;
  onOpenWalk: () => void;
};

const BANQUET = new Set(["banqueting", "banquet_buffet"]);

export function BoardPage({
  serviceDate,
  section,
  onBack,
  onOpenWalk,
}: Props) {
  const qc = useQueryClient();
  const [face, setFace] = useState<BoardFace>(() => {
    const ctx = readStationContext();
    return ctx && ctx.section === section && ctx.serviceDate === serviceDate
      ? ctx.face
      : "mep";
  });
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickName, setQuickName] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [modeBusy, setModeBusy] = useState(false);
  const [modeReceipt, setModeReceipt] = useState<string | null>(null);
  const [coversDraft, setCoversDraft] = useState<string | null>(null);

  const key = ["board", serviceDate, section] as const;
  const title =
    SECTION_LABELS[section as SectionId] ?? section.replace(/_/g, " ");
  const isBanquet = BANQUET.has(section);

  const boardQ = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      try {
        return await getBoard(serviceDate, section, signal);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          return openSection(
            serviceDate,
            section,
            { generate_lines: true },
            signal,
          );
        }
        throw e;
      }
    },
    retry: 1,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: key });

  const openMut = useMutation({
    mutationFn: () =>
      openSection(serviceDate, section, { generate_lines: true }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
    },
  });

  const quickMut = useMutation({
    mutationFn: (name: string) =>
      quickAddLine({
        service_date: serviceDate,
        section,
        name,
        mode: defaultQuickAddMode(section),
        kind: "dish",
        notes: "",
      }),
    onSuccess: async () => {
      setQuickName("");
      setQuickOpen(false);
      await invalidate();
    },
    onError: (e) => {
      setActionError(e instanceof Error ? e.message : "Quick-add failed");
    },
  });

  const scaleMut = useMutation({
    mutationFn: () => scaleProduce(serviceDate, section),
    onSuccess: async () => {
      setActionError(null);
      await invalidate();
    },
    onError: (e) => {
      setActionError(e instanceof Error ? e.message : "Scale failed");
    },
  });

  const coversMut = useMutation({
    mutationFn: (covers: number) =>
      patchSectionCovers(serviceDate, section, {
        covers,
        covers_source: "manual",
      }),
    onSuccess: async (data) => {
      qc.setQueryData(key, data);
      setCoversDraft(null);
      setActionError(null);
    },
    onError: (e) => {
      setActionError(e instanceof Error ? e.message : "Could not save covers");
    },
  });

  const lines = useMemo(() => {
    const list = boardQ.data?.lines ?? [];
    return list
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
  }, [boardQ.data?.lines]);

  const stats = useMemo(() => {
    let done = 0;
    let eightySix = 0;
    for (const l of lines) {
      if (isEightySix(l.status)) eightySix += 1;
      else if (l.ticked) done += 1;
    }
    const total = lines.length;
    return {
      done,
      left: Math.max(0, total - done - eightySix),
      eightySix,
      total,
    };
  }, [lines]);

  async function runLine(line: ProductionLineOut, fn: () => Promise<unknown>) {
    setActionError(null);
    setBusyId(line.id);
    try {
      await fn();
      await invalidate();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  function pickFace(next: BoardFace) {
    setFace(next);
    rememberFace(serviceDate, section, next);
  }

  async function chooseMode(mode: SectionMode, guided?: boolean) {
    setModeBusy(true);
    setActionError(null);
    try {
      const body =
        guided === undefined ? { mode } : { mode, guided };
      await patchSectionSettings(section, body);
      setModeReceipt(
        mode === "counts"
          ? "Counts — quantities tracked"
          : "Ordering — menu + what to order",
      );
      await invalidate();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not set mode");
    } finally {
      setModeBusy(false);
    }
  }

  if (boardQ.isLoading) {
    return <LoadingState label="Loading board…" />;
  }

  if (boardQ.isError) {
    const err = boardQ.error;
    const msg =
      err instanceof ApiError
        ? err.status === 401
          ? "Session expired — sign in again (local walk data kept)."
          : err.message
        : "Could not load board";
    return (
      <div className="stack">
        <button type="button" className="link-back" onClick={onBack}>
          ← Station log
        </button>
        <EmptyState
          title="Board unavailable"
          body={msg}
          action={
            <button
              type="button"
              className="btn btn--primary btn--block"
              onClick={() => openMut.mutate()}
              disabled={openMut.isPending}
            >
              {openMut.isPending ? "Opening…" : "Retry open section"}
            </button>
          }
        />
      </div>
    );
  }

  const board = boardQ.data!;
  const empty = lines.length === 0;
  const sectionMode =
    board.section_mode === "counts" || board.section_mode === "ordering"
      ? (board.section_mode as SectionMode)
      : null;
  const modePrompt = Boolean(board.mode_prompt_needed);
  const guided = Boolean(board.guided);
  const serviceCheck =
    face === "service" &&
    (section === "skybar" || section === "a_la_carte");
  const serviceReplenish =
    face === "service" && section === "breakfast_buffet";
  const coversValue =
    coversDraft ?? (board.covers != null ? String(board.covers) : "");

  return (
    <div className="stack board-page">
      <div className="board-page__top">
        <button type="button" className="link-back" onClick={onBack}>
          ← Station log
        </button>
        <div>
          <h2 className="page-title">
            {title} <ModePill mode={sectionMode} guided={guided} />
          </h2>
          <p className="page-lead" style={{ marginBottom: 0 }}>
            {serviceDate} · {face === "mep" ? "Prep" : "Service"}
            {!board.active ? " · inactive" : ""}
            {serviceCheck ? " · fire-to-order + 86" : ""}
            {serviceReplenish ? " · replenish (pars when set)" : ""}
          </p>
        </div>

        <div className="face-toggle" role="tablist" aria-label="Board face">
          <button
            type="button"
            role="tab"
            aria-selected={face === "mep"}
            className={`face-toggle__btn${face === "mep" ? " is-on" : ""}`}
            onClick={() => pickFace("mep")}
          >
            Prep
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={face === "service"}
            className={`face-toggle__btn${face === "service" ? " is-on" : ""}`}
            onClick={() => pickFace("service")}
          >
            Service
          </button>
        </div>

        {sectionMode !== "ordering" ? (
          <div className="progress-strip" aria-live="polite">
            <span className="num num--actual">{stats.done}</span>
            <span className="progress-strip__label">done</span>
            <span className="num num--proposed">{stats.left}</span>
            <span className="progress-strip__label">left</span>
            <span className="num num--diverged">{stats.eightySix}</span>
            <span className="progress-strip__label">86</span>
            <span className="num num--planned">{stats.total}</span>
            <span className="progress-strip__label">total</span>
          </div>
        ) : (
          <div className="progress-strip" aria-live="polite">
            <span className="num num--planned">{stats.total}</span>
            <span className="progress-strip__label">dishes</span>
            <span className="num num--diverged">{stats.eightySix}</span>
            <span className="progress-strip__label">86</span>
          </div>
        )}

        <button
          type="button"
          className="btn btn--ghost btn--block"
          disabled={openMut.isPending}
          onClick={() => openMut.mutate()}
        >
          {openMut.isPending ? "Updating…" : "Update menu"}
        </button>
      </div>

      {actionError ? <p className="field__error">{actionError}</p> : null}

      {modePrompt ? (
        <ModePrompt
          section={section}
          recommendation={board.mode_recommendation}
          guidedDefault={board.guided}
          busy={modeBusy}
          onChoose={chooseMode}
        />
      ) : null}

      {modeReceipt && !modePrompt ? (
        <p className="mode-receipt">{modeReceipt}</p>
      ) : null}

      <StationLogPanel
        serviceDate={serviceDate}
        section={section}
        compact
        onOpenWalk={onOpenWalk}
      />

      {isBanquet ? (
        <div className="banquet-scale">
          <label className="field">
            <span className="field__label">Covers</span>
            <input
              className="field__input"
              inputMode="numeric"
              value={coversValue}
              onChange={(e) => setCoversDraft(e.target.value)}
              placeholder="e.g. 120"
            />
          </label>
          <div className="banquet-scale__row">
            <button
              type="button"
              className="btn btn--ghost"
              disabled={coversMut.isPending || coversValue.trim() === ""}
              onClick={() => {
                const n = Number(coversValue);
                if (!Number.isFinite(n) || n < 0) {
                  setActionError("Covers must be a number");
                  return;
                }
                coversMut.mutate(Math.floor(n));
              }}
            >
              {coversMut.isPending ? "Saving…" : "Save covers"}
            </button>
            <button
              type="button"
              className="btn btn--primary"
              disabled={scaleMut.isPending}
              onClick={() => scaleMut.mutate()}
            >
              {scaleMut.isPending ? "Scaling…" : "Scale produce"}
            </button>
          </div>
          {scaleMut.data ? (
            <p className="board-row__meta">
              Scaled {scaleMut.data.updated.length} line
              {scaleMut.data.updated.length === 1 ? "" : "s"}
              {scaleMut.data.scaling_covers != null
                ? ` · ${scaleMut.data.scaling_covers} covers`
                : " · no covers"}
              {scaleMut.data.skipped_null_path.length
                ? ` · ${scaleMut.data.skipped_null_path.length} skipped (no yield)`
                : ""}
            </p>
          ) : null}
        </div>
      ) : null}

      {empty ? (
        <EmptyState
          title="No lines yet"
          body="Partial catalogue is normal. Quick-add a prep line — or Update menu to pull templates."
          action={
            !quickOpen ? (
              <button
                type="button"
                className="btn btn--primary btn--block"
                onClick={() => setQuickOpen(true)}
              >
                + Quick-add line
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="board">
          <div className="board__section-label">
            {sectionMode === "ordering"
              ? "Menu"
              : face === "mep"
                ? "Prep"
                : "Service"}
          </div>
          {lines.map((line) => (
            <BoardLine
              key={line.id}
              line={line}
              face={face}
              section={section}
              sectionMode={sectionMode}
              busy={busyId === line.id}
              onTickLine={(l) => runLine(l, () => tickLine(l.id, null))}
              onUntickLine={(l) => runLine(l, () => untickLine(l.id))}
              onSetEightySix={(l) =>
                runLine(l, () => tickLine(l.id, { status: "eighty_six" }))
              }
              onTickComponent={async (id, done) => {
                setBusyId(line.id);
                setActionError(null);
                try {
                  if (done) await untickComponent(id);
                  else await tickComponent(id);
                  await invalidate();
                } catch (e) {
                  setActionError(
                    e instanceof Error ? e.message : "Component tick failed",
                  );
                } finally {
                  setBusyId(null);
                }
              }}
              onSaveNotes={async (l, notes) => {
                setBusyId(l.id);
                setActionError(null);
                try {
                  await setLineNotes(l.id, {
                    notes: notes.trim() ? notes : null,
                  });
                  await invalidate();
                } catch (e) {
                  setActionError(
                    e instanceof Error ? e.message : "Note save failed",
                  );
                  throw e;
                } finally {
                  setBusyId(null);
                }
              }}
            />
          ))}
        </div>
      )}

      {quickOpen || !empty ? (
        <div className="quick-add">
          {!quickOpen ? (
            <button
              type="button"
              className="btn btn--ghost btn--block"
              onClick={() => setQuickOpen(true)}
            >
              + Quick-add line
            </button>
          ) : (
            <>
              <label className="field__label" htmlFor="qa-name">
                Line name
              </label>
              <div className="quick-add__row">
                <input
                  id="qa-name"
                  className="field__input"
                  value={quickName}
                  onChange={(e) => setQuickName(e.target.value)}
                  placeholder="e.g. lemon wedges"
                  autoFocus
                />
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={!quickName.trim() || quickMut.isPending}
                  onClick={() => quickMut.mutate(quickName.trim())}
                >
                  Add
                </button>
              </div>
              <button
                type="button"
                className="link-back"
                onClick={() => setQuickOpen(false)}
              >
                Cancel
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

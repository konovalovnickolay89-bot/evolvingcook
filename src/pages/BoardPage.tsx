import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getBoard,
  openSection,
  quickAddLine,
  setLineNotes,
  tickComponent,
  tickLine,
  untickComponent,
  untickLine,
} from "@/api/boards";
import { listProposals } from "@/api/assist";
import { ApiError } from "@/api/client";
import type { ProductionLineOut, ProposalOut } from "@/api/types";
import { BoardLine } from "@/components/BoardLine";
import { ProposalCard } from "@/components/ProposalCard";
import { EmptyState, LoadingState } from "@/components/AppShell";
import { defaultQuickAddMode, SECTION_LABELS, type SectionId } from "@/contract";
import { isEightySix } from "@/lib/lineDisplay";
import { acceptProposal, rejectProposal } from "@/api/assist";

export type BoardFace = "mep" | "service";

type Props = {
  serviceDate: string;
  section: string;
  onBack: () => void;
};

export function BoardPage({ serviceDate, section, onBack }: Props) {
  const qc = useQueryClient();
  const [face, setFace] = useState<BoardFace>("mep");
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickName, setQuickName] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [propBusy, setPropBusy] = useState<number | null>(null);

  const key = ["board", serviceDate, section] as const;
  const title =
    SECTION_LABELS[section as SectionId] ?? section.replace(/_/g, " ");

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

  const draftPropsQ = useQuery({
    queryKey: ["proposals", "board", section, serviceDate],
    queryFn: async ({ signal }) => {
      const all = await listProposals({ status: "pending", limit: 50 }, signal);
      return all.filter((p) => {
        const c = p.context as { section?: string; service_date?: string };
        if (c.section && c.section === section) return true;
        if (p.kind === "draft_prep" || p.kind === "prep_line") {
          return c.section === section || !c.section;
        }
        return false;
      });
    },
    retry: false,
    refetchInterval: 10000,
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

  async function onAccept(p: ProposalOut) {
    setPropBusy(p.id);
    try {
      await acceptProposal(p.id);
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await invalidate();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Accept failed");
    } finally {
      setPropBusy(null);
    }
  }

  async function onReject(p: ProposalOut, reason: string) {
    setPropBusy(p.id);
    try {
      await rejectProposal(p.id, { reason });
      await qc.invalidateQueries({ queryKey: ["proposals"] });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setPropBusy(null);
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
          ← Day home
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
  const draftProps = draftPropsQ.data ?? [];
  const serviceCheck =
    face === "service" &&
    (section === "skybar" || section === "a_la_carte");
  const serviceReplenish =
    face === "service" && section === "breakfast_buffet";

  return (
    <div className="stack board-page">
      <div className="board-page__top">
        <button type="button" className="link-back" onClick={onBack}>
          ← Day home
        </button>
        <div>
          <h2 className="page-title">{title}</h2>
          <p className="page-lead" style={{ marginBottom: 0 }}>
            {serviceDate} ·{" "}
            {face === "mep" ? "MEP (pre-service)" : "Service"}
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
            onClick={() => setFace("mep")}
          >
            MEP
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={face === "service"}
            className={`face-toggle__btn${face === "service" ? " is-on" : ""}`}
            onClick={() => setFace("service")}
          >
            Service
          </button>
        </div>

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
      </div>

      {actionError ? <p className="field__error">{actionError}</p> : null}

      {draftProps.length > 0 ? (
        <div className="stack" style={{ gap: "var(--space-02)" }}>
          <div className="board__section-label">
            proposed — not accepted
          </div>
          {draftProps.map((p) => (
            <ProposalCard
              key={p.id}
              proposal={p}
              busy={propBusy === p.id}
              onAccept={onAccept}
              onReject={onReject}
            />
          ))}
        </div>
      ) : null}

      {empty ? (
        <EmptyState
          title="No lines yet"
          body="Partial catalogue is normal. Quick-add a prep line — faster than the clipboard margin."
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
            {face === "mep" ? "Mise en place" : "Live service"} · {section}
          </div>
          {lines.map((line) => (
            <BoardLine
              key={line.id}
              line={line}
              face={face}
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
                    e instanceof Error ? e.message : "Component update failed",
                  );
                } finally {
                  setBusyId(null);
                }
              }}
              onSaveNotes={async (l, notes) => {
                await runLine(l, () =>
                  setLineNotes(l.id, { notes: notes.trim() || null }),
                );
              }}
            />
          ))}
        </div>
      )}

      <div className="quick-add">
        {!quickOpen ? (
          <button
            type="button"
            className="btn btn--primary btn--block"
            onClick={() => setQuickOpen(true)}
          >
            + Quick-add line
          </button>
        ) : (
          <form
            className="quick-add__form"
            onSubmit={(e) => {
              e.preventDefault();
              const name = quickName.trim();
              if (!name) return;
              quickMut.mutate(name);
            }}
          >
            <input
              className="field__input"
              placeholder="Line name"
              value={quickName}
              onChange={(e) => setQuickName(e.target.value)}
              autoFocus
              enterKeyHint="done"
              autoCapitalize="sentences"
            />
            <div className="quick-add__row">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setQuickOpen(false);
                  setQuickName("");
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={!quickName.trim() || quickMut.isPending}
              >
                {quickMut.isPending ? "Adding…" : "Add"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

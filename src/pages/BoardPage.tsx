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
import { listProposals, acceptProposal, rejectProposal } from "@/api/assist";
import { patchSectionSettings } from "@/api/sections";
import { ApiError } from "@/api/client";
import type { ProductionLineOut, ProposalOut } from "@/api/types";
import { BoardLine } from "@/components/BoardLine";
import { ProposalCard } from "@/components/ProposalCard";
import { ModePill, ModePrompt } from "@/components/ModePrompt";
import { OrderAssistCard } from "@/components/OrderAssistCard";
import { PrepPlanStrip } from "@/components/PrepPlanStrip";
import { QtyDraftStrip } from "@/components/QtyDraftStrip";
import { EmptyState, LoadingState } from "@/components/AppShell";
import {
  defaultQuickAddMode,
  SECTION_LABELS,
  type SectionId,
  type SectionMode,
} from "@/contract";
import { isEightySix } from "@/lib/lineDisplay";
import {
  parseOrderAssist,
  parsePrepPlan,
  parseQtyDraft,
  type QtyDraftItem,
  type PrepStep,
} from "@/lib/boardDepth";

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
  const [modeBusy, setModeBusy] = useState(false);
  const [modeReceipt, setModeReceipt] = useState<string | null>(null);

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
    refetchInterval: (q) => {
      const lines = q.state.data?.lines ?? [];
      const anyPending = lines.some((l) => l.pending_proposal);
      const draft = parseQtyDraft(q.state.data?.qty_draft);
      const prep = parsePrepPlan(q.state.data?.prep_plan);
      const assistPending =
        (draft?.items.some((i) => i.status === "pending") ?? false) ||
        (prep?.steps.some((s) => s.status === "pending") ?? false);
      return anyPending || assistPending ? 4000 : false;
    },
  });

  const draftPropsQ = useQuery({
    queryKey: ["proposals", "board", section, serviceDate],
    queryFn: async ({ signal }) => {
      const all = await listProposals({ status: "pending", limit: 50 }, signal);
      // Strip: non-line drafts not already on board strips
      return all.filter((p) => {
        if (p.parse_error?.trim()) return false;
        if (p.kind === "parse_note") return false;
        if (
          p.kind === "qty_draft" ||
          p.kind === "morning_qty" ||
          p.kind === "order_suggest" ||
          p.kind === "prep_plan" ||
          p.target === "prep_step" ||
          p.target === "planned_qty" ||
          p.target === "order_packs"
        ) {
          // Surfaced via board.qty_draft / prep_plan / order_assist
          return false;
        }
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
      await invalidate();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setPropBusy(null);
    }
  }

  async function chooseMode(mode: SectionMode, guided?: boolean) {
    setModeBusy(true);
    setActionError(null);
    try {
      const body =
        guided === undefined
          ? { mode }
          : { mode, guided };
      const res = await patchSectionSettings(section, body);
      setModeReceipt(
        mode === "counts"
          ? "Counts — quantities tracked"
          : "Ordering — menu + what to order",
      );
      await invalidate();
      void res;
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not set mode");
    } finally {
      setModeBusy(false);
    }
  }

  async function acceptWithOverlay(
    proposalId: number,
    overlay?: Record<string, unknown>,
  ) {
    setPropBusy(proposalId);
    setActionError(null);
    try {
      await acceptProposal(
        proposalId,
        overlay ? { proposal: overlay } : null,
      );
      await invalidate();
      await qc.invalidateQueries({ queryKey: ["proposals"] });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Accept failed");
    } finally {
      setPropBusy(null);
    }
  }

  async function passProposal(proposalId: number) {
    setPropBusy(proposalId);
    setActionError(null);
    try {
      await rejectProposal(proposalId, { reason: "" });
      await invalidate();
      await qc.invalidateQueries({ queryKey: ["proposals"] });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Pass failed");
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
  const sectionMode =
    board.section_mode === "counts" || board.section_mode === "ordering"
      ? (board.section_mode as SectionMode)
      : null;
  const modePrompt = Boolean(board.mode_prompt_needed) || sectionMode == null;
  const guided = Boolean(board.guided);
  const orderAssist =
    sectionMode === "ordering" ? parseOrderAssist(board.order_assist) : null;
  const qtyDraft =
    sectionMode === "counts" ? parseQtyDraft(board.qty_draft) : null;
  const prepPlan =
    sectionMode === "counts" && guided
      ? parsePrepPlan(board.prep_plan)
      : null;

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
          <h2 className="page-title">
            {title}{" "}
            <ModePill mode={sectionMode} guided={guided} />
          </h2>
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

      {orderAssist ? (
        <OrderAssistCard
          card={orderAssist}
          busy={propBusy === orderAssist.proposal_id}
          onAccept={() => void acceptWithOverlay(orderAssist.proposal_id)}
          onPass={() => void passProposal(orderAssist.proposal_id)}
        />
      ) : null}

      {prepPlan ? (
        <PrepPlanStrip
          plan={prepPlan}
          busyId={propBusy}
          onAccept={(step: PrepStep, overlay) =>
            void acceptWithOverlay(step.proposal_id, overlay)
          }
          onPass={(step) => void passProposal(step.proposal_id)}
        />
      ) : null}

      {qtyDraft ? (
        <QtyDraftStrip
          draft={qtyDraft}
          busyId={propBusy}
          onAccept={(item: QtyDraftItem, overlay) =>
            void acceptWithOverlay(item.proposal_id, overlay)
          }
          onPass={(item) => void passProposal(item.proposal_id)}
        />
      ) : null}

      {draftProps.length > 0 ? (
        <div className="stack" style={{ gap: "var(--space-02)" }}>
          <div className="board__section-label">proposed — not accepted</div>
          {draftProps.map((p) => (
            <ProposalCard
              key={p.id}
              proposal={p}
              compact
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
            {sectionMode === "ordering"
              ? "Menu"
              : face === "mep"
                ? "Mise en place"
                : "Live service"}{" "}
            · {section}
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

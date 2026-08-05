import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProductionLineOut, ProposalOut } from "@/api/types";
import { createAssistJob } from "@/api/assist";
import { acceptProposal, rejectProposal } from "@/api/assist";
import { BoardRow, type NoteAssistState } from "./BoardRow";
import { ProposalCard } from "./ProposalCard";
import {
  checkStateFromLine,
  lineBreakdown,
  lineMeta,
  normalizeMode,
  produceNums,
  replenishNums,
} from "@/lib/lineDisplay";
import { formatDecimal } from "@/lib/decimal";
import {
  coercePendingProposal,
  parseNoteContext,
} from "@/lib/proposalTarget";
import type { BoardFace } from "@/pages/BoardPage";

type Props = {
  line: ProductionLineOut;
  face?: BoardFace;
  section?: string;
  busy?: boolean;
  onTickLine: (line: ProductionLineOut) => void;
  onUntickLine: (line: ProductionLineOut) => void;
  onSetEightySix: (line: ProductionLineOut) => void;
  onTickComponent: (componentId: number, done: boolean) => void;
  onSaveNotes?: (line: ProductionLineOut, notes: string) => Promise<void> | void;
};

export function BoardLine({
  line,
  face = "mep",
  section,
  busy,
  onTickLine,
  onUntickLine,
  onSetEightySix,
  onTickComponent,
  onSaveNotes,
}: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState(line.notes || "");
  const [assistState, setAssistState] = useState<NoteAssistState>("idle");
  const [actionBusy, setActionBusy] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const mode = normalizeMode(line.mode);
  const meta = lineMeta(line);
  const breakdown = lineBreakdown(line);
  const houseMade = Boolean(line.item_house_made);
  const doneCount = line.components.filter((c) => c.done).length;
  const totalComp = line.components.length;
  const showAs = mode;

  const pendingInline = useMemo(
    () => coercePendingProposal(line.pending_proposal, line.id),
    [line.pending_proposal, line.id],
  );

  useEffect(() => {
    setNoteDraft(line.notes || "");
  }, [line.notes, line.id]);

  // Drive chip from payload: pending → ready; else keep local parsing until silence
  useEffect(() => {
    if (pendingInline) {
      setAssistState("ready");
      return;
    }
    setAssistState((prev) => (prev === "ready" ? "idle" : prev));
  }, [pendingInline]);

  async function saveNoteOnly() {
    if (!onSaveNotes) return;
    setSaveMsg(null);
    const text = noteDraft.trim();
    await onSaveNotes(line, noteDraft);

    // Instant chip; silence if empty (no structure to parse)
    if (!text) {
      setAssistState("idle");
      return;
    }

    setAssistState("parsing");

    // Typed context only (D14). Server also auto-enqueues on note-save;
    // client job ensures parse when A2A path needs an explicit enqueue.
    const sectionKey = section || line.category || "";
    try {
      await createAssistJob({
        kind: "parse_note",
        context: parseNoteContext({
          text,
          line_id: line.id,
          section: sectionKey,
        }),
      });
    } catch {
      // Auto-enqueue may already have fired — keep polling board.
    }

    // Poll board until pending_proposal or silence (no structure)
    const started = Date.now();
    const poll = async () => {
      await qc.invalidateQueries({ queryKey: ["board"] });
      // parent refresh updates line; if still parsing after timeout → silence
      if (Date.now() - started > 25_000) {
        setAssistState((s) => (s === "parsing" ? "idle" : s));
        return;
      }
      window.setTimeout(() => {
        void poll();
      }, 2000);
    };
    window.setTimeout(() => {
      void poll();
    }, 1200);
  }

  async function onAccept(p: ProposalOut) {
    setActionBusy(true);
    try {
      await acceptProposal(p.id);
      setAssistState("idle");
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await qc.invalidateQueries({ queryKey: ["board"] });
    } finally {
      setActionBusy(false);
    }
  }

  async function onReject(p: ProposalOut, reason: string) {
    setActionBusy(true);
    try {
      await rejectProposal(p.id, { reason });
      setAssistState("idle");
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await qc.invalidateQueries({ queryKey: ["board"] });
    } finally {
      setActionBusy(false);
    }
  }

  const templateNotes = (line.template_notes || "").trim();
  const lineNotes = (line.notes || "").trim();

  return (
    <div
      className={`board-line${busy ? " is-busy" : ""}${open ? " is-open" : ""}${
        face === "service" ? " board-line--service" : ""
      }`}
    >
      <BoardRow
        mode={showAs}
        name={line.name}
        houseMade={houseMade}
        noteChip={lineNotes || null}
        templateNoteChip={templateNotes || null}
        noteAssistState={assistState}
        meta={
          totalComp
            ? `${meta ? `${meta} · ` : ""}${doneCount}/${totalComp} components`
            : meta || undefined
        }
        produce={showAs === "produce" ? produceNums(line) : undefined}
        replenish={showAs === "replenish" ? replenishNums(line) : undefined}
        check={showAs === "check" ? checkStateFromLine(line) : undefined}
        breakdown={undefined}
        onActivate={() => {
          setNoteDraft(line.notes || "");
          setOpen((v) => !v);
        }}
      />

      {open ? (
        <div className="board-line__actions">
          {line.supports_lounge ? (
            <span className="covers-chip">covers: lounge</span>
          ) : null}

          {/* Inline pending proposal first — one-handed accept in the row (D14) */}
          {pendingInline ? (
            <div className="stack" style={{ gap: "var(--space-02)" }}>
              <div className="board__section-label">proposal · not accepted</div>
              <ProposalCard
                proposal={pendingInline}
                busy={actionBusy}
                onAccept={onAccept}
                onReject={onReject}
              />
            </div>
          ) : null}

          {showAs === "check" ? (
            <div className="board-line__checks">
              <button
                type="button"
                className={`chip${checkStateFromLine(line) === "present" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onUntickLine(line)}
              >
                Present
              </button>
              <button
                type="button"
                className={`chip chip--ok${checkStateFromLine(line) === "confirm" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onTickLine(line)}
              >
                Confirm
              </button>
              <button
                type="button"
                className={`chip chip--danger${checkStateFromLine(line) === "86" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onSetEightySix(line)}
              >
                86
              </button>
            </div>
          ) : (
            <div className="board-line__checks">
              <button
                type="button"
                className={`chip${line.ticked ? " is-on chip--ok" : ""}`}
                disabled={busy}
                onClick={() =>
                  line.ticked ? onUntickLine(line) : onTickLine(line)
                }
              >
                {line.ticked ? "Done ✓" : "Mark done"}
              </button>
            </div>
          )}

          {totalComp > 0 ? (
            <div>
              <div className="board__section-label">
                {houseMade ? "House-made constituents" : "Components"}
              </div>
              <ul className="component-list">
                {line.components
                  .slice()
                  .sort((a, b) => a.sort_order - b.sort_order)
                  .map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        className={`component-row${c.done ? " is-done" : ""}`}
                        disabled={busy}
                        onClick={() => onTickComponent(c.id, c.done)}
                      >
                        <span className="component-row__box" aria-hidden>
                          {c.done ? "✓" : ""}
                        </span>
                        <span className="component-row__name">
                          {c.name}
                          {c.supplier_item_id != null ? (
                            <span className="component-row__code">
                              {" "}
                              · #{c.supplier_item_id}
                            </span>
                          ) : null}
                        </span>
                        <span className="component-row__qty num">
                          {formatDecimal(c.planned_qty)}
                          {c.unit ? ` ${c.unit}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ) : null}

          {onSaveNotes ? (
            <div className="note-edit">
              <label className="field__label" htmlFor={`note-${line.id}`}>
                Note
              </label>
              <input
                id={`note-${line.id}`}
                className="field__input"
                type="text"
                enterKeyHint="done"
                autoComplete="off"
                maxLength={500}
                value={noteDraft}
                disabled={busy}
                onChange={(e) => setNoteDraft(e.target.value)}
                placeholder="Type or dictate a note"
              />
              <div className="quick-add__row">
                <button
                  type="button"
                  className="btn btn--primary btn--block"
                  disabled={busy || noteDraft === (line.notes || "")}
                  onClick={() => {
                    void saveNoteOnly().catch((e) =>
                      setSaveMsg(
                        e instanceof Error ? e.message : "Save failed",
                      ),
                    );
                  }}
                >
                  Save
                </button>
              </div>
              {saveMsg ? <p className="field__error">{saveMsg}</p> : null}
            </div>
          ) : null}

          <div className="board-row-detail" style={{ padding: 0, border: 0 }}>
            <div className="board-row-detail__grid">
              {breakdown.map((row) => (
                <div key={row.label} style={{ display: "contents" }}>
                  <span className="board-row-detail__k">{row.label}</span>
                  <span className="board-row-detail__v">{row.value}</span>
                </div>
              ))}
              {houseMade ? (
                <>
                  <span className="board-row-detail__k">House made</span>
                  <span className="board-row-detail__v">yes</span>
                </>
              ) : null}
              {templateNotes ? (
                <>
                  <span className="board-row-detail__k">Template note</span>
                  <span className="board-row-detail__v">↻ {templateNotes}</span>
                </>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

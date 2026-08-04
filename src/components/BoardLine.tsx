import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProductionLineOut, ProposalOut } from "@/api/types";
import {
  createAssistJob,
  getAssistJob,
  listProposals,
  acceptProposal,
  rejectProposal,
} from "@/api/assist";
import { BoardRow } from "./BoardRow";
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
import type { BoardFace } from "@/pages/BoardPage";

type Props = {
  line: ProductionLineOut;
  face?: BoardFace;
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
  const [jobId, setJobId] = useState<number | null>(null);
  const [jobMsg, setJobMsg] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const mode = normalizeMode(line.mode);
  const meta = lineMeta(line);
  const breakdown = lineBreakdown(line);
  const houseMade = Boolean(line.item_house_made);
  const doneCount = line.components.filter((c) => c.done).length;
  const totalComp = line.components.length;
  const showAs = mode;

  useEffect(() => {
    setNoteDraft(line.notes || "");
  }, [line.notes, line.id]);

  const linePropsQ = useQuery({
    queryKey: ["proposals", "line", line.id],
    queryFn: async ({ signal }) => {
      const all = await listProposals({ limit: 50 }, signal);
      return all.filter((p) => {
        const c = p.context as { line_id?: number };
        return c.line_id === line.id;
      });
    },
    enabled: open,
    refetchInterval: open ? 4000 : false,
    retry: false,
  });

  const jobQ = useQuery({
    queryKey: ["assist-job", jobId],
    queryFn: ({ signal }) => getAssistJob(jobId!, signal),
    enabled: jobId != null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "queued" || s === "running" || s === "pending") return 1500;
      return false;
    },
    retry: false,
  });

  useEffect(() => {
    if (!jobQ.data) return;
    if (jobQ.data.status === "failed") {
      setJobMsg(
        jobQ.data.error?.includes("A2A") || jobQ.data.error?.includes("unreachable")
          ? "assist offline"
          : jobQ.data.error || "Job failed",
      );
    }
    if (jobQ.data.status === "done" || jobQ.data.status === "completed") {
      void qc.invalidateQueries({ queryKey: ["proposals"] });
      void qc.invalidateQueries({ queryKey: ["proposals", "line", line.id] });
    }
  }, [jobQ.data, qc, line.id]);

  const pendingForLine = (linePropsQ.data ?? []).filter(
    (p) => p.status === "pending",
  );
  const recentForLine = (linePropsQ.data ?? []).filter(
    (p) => p.status !== "pending",
  ).slice(0, 2);

  async function saveAndMaybeParse() {
    if (!onSaveNotes) return;
    setJobMsg(null);
    await onSaveNotes(line, noteDraft);
    const text = noteDraft.trim();
    if (!text) return;
    try {
      const job = await createAssistJob({
        kind: "parse_note",
        context: {
          line_id: line.id,
          notes: text,
          section: line.category || undefined,
          item_id: line.item_id,
        },
      });
      setJobId(job.id);
      if (job.status === "failed") {
        setJobMsg(
          job.error?.includes("A2A") || job.error?.includes("unreachable")
            ? "assist offline"
            : job.error || "Job failed",
        );
      }
    } catch (e) {
      setJobMsg(
        e instanceof Error && /A2A|unreachable|fetch|network/i.test(e.message)
          ? "assist offline"
          : e instanceof Error
            ? e.message
            : "Could not start parse",
      );
    }
  }

  async function onAccept(p: ProposalOut) {
    setActionBusy(true);
    try {
      await acceptProposal(p.id);
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
      await qc.invalidateQueries({ queryKey: ["proposals"] });
    } finally {
      setActionBusy(false);
    }
  }

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
        noteChip={line.notes ? line.notes : null}
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

          {/* Components always — for house_made show as constituent breakdown */}
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
                  className="btn btn--ghost"
                  disabled={busy || noteDraft === (line.notes || "")}
                  onClick={() => void saveAndMaybeParse()}
                >
                  Save note
                </button>
              </div>
              {jobMsg ? (
                <p className="board-row__meta" style={{ color: "var(--comment)" }}>
                  {jobMsg}
                </p>
              ) : null}
              {jobQ.data &&
              (jobQ.data.status === "queued" ||
                jobQ.data.status === "running") ? (
                <p className="board-row__meta">Parsing note…</p>
              ) : null}
            </div>
          ) : null}

          {pendingForLine.length > 0 ? (
            <div className="stack" style={{ gap: "var(--space-02)" }}>
              <div className="board__section-label">parse_note · not accepted</div>
              {pendingForLine.map((p) => (
                <ProposalCard
                  key={p.id}
                  proposal={p}
                  busy={actionBusy}
                  onAccept={onAccept}
                  onReject={onReject}
                />
              ))}
            </div>
          ) : null}

          {recentForLine.length > 0 && pendingForLine.length === 0 ? (
            <div className="stack" style={{ gap: "var(--space-02)" }}>
              {recentForLine.map((p) => (
                <ProposalCard
                  key={p.id}
                  proposal={p}
                  busy={actionBusy}
                  onAccept={onAccept}
                  onReject={onReject}
                  compact
                />
              ))}
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
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

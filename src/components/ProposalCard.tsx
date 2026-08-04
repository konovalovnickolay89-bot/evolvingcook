import { useState } from "react";
import type { ProposalOut } from "@/api/types";
import { PROPOSAL_REJECT_REASONS } from "@/contract";
import { formatDecimal } from "@/lib/decimal";

type Props = {
  proposal: ProposalOut;
  busy?: boolean;
  /** low confidence: require expanded before accept (§10d) */
  onAccept: (p: ProposalOut) => void;
  onReject: (p: ProposalOut, reason: string) => void;
  compact?: boolean;
};

function confidenceOf(p: ProposalOut): "high" | "med" | "low" {
  const raw =
    (p.proposal as { confidence?: number | string })?.confidence ??
    (p.context as { confidence?: number | string })?.confidence;
  const n = typeof raw === "number" ? raw : Number(raw);
  if (Number.isFinite(n)) {
    if (n >= 0.75) return "high";
    if (n >= 0.45) return "med";
    return "low";
  }
  // empty model/rationale from gate → treat as med
  if (!p.rationale && !p.model) return "med";
  return "med";
}

function summaryLine(p: ProposalOut): string {
  const prop = p.proposal as Record<string, unknown>;
  if (typeof prop.note === "string" && prop.note) return prop.note;
  if (typeof prop.summary === "string" && prop.summary) return prop.summary;
  if (p.kind === "parse_note") {
    const text =
      (p.context as { notes?: string; text?: string }).notes ||
      (p.context as { text?: string }).text ||
      "";
    return text ? `Parse note: ${text.slice(0, 80)}` : "Parse note";
  }
  return p.kind.replace(/_/g, " ");
}

function contextChip(p: ProposalOut): string {
  const c = p.context as Record<string, unknown>;
  if (typeof c.section === "string") return c.section;
  if (c.line_id != null) return `line ${c.line_id}`;
  if (c.item_id != null) return `item ${c.item_id}`;
  return p.kind;
}

function ageLabel(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export function ProposalCard({
  proposal,
  busy,
  onAccept,
  onReject,
  compact,
}: Props) {
  const [open, setOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [otherNote, setOtherNote] = useState("");
  const conf = confidenceOf(proposal);
  const pending = proposal.status === "pending";
  const prop = proposal.proposal as Record<string, unknown>;
  const components = Array.isArray(prop.components)
    ? (prop.components as Array<Record<string, unknown>>)
    : [];
  const houseMade = Boolean(prop.house_made);

  const canSwipeAccept = conf !== "low";

  return (
    <article
      className={`proposal-card${pending ? " proposal-card--pending" : ""}${
        open ? " is-open" : ""
      }`}
    >
      <button
        type="button"
        className="proposal-card__main"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="board-row__badge board-row__badge--assist" aria-label="assist">
          A
        </span>
        <div className="board-row__main">
          <span className="board-row__name proposal-card__title">
            {summaryLine(proposal)}
          </span>
          <span className="board-row__meta">
            {contextChip(proposal)}
            {" · "}
            <span className={`conf-chip conf-chip--${conf}`}>{conf}</span>
            {" · "}
            {ageLabel(proposal.created_at)}
            {!pending ? ` · ${proposal.status}` : ""}
          </span>
        </div>
        {houseMade ? (
          <span className="house-tag" title="house made">
            H
          </span>
        ) : null}
      </button>

      {open || !compact ? (
        <div className="proposal-card__body">
          {proposal.rationale ? (
            <p className="proposal-card__rationale">{proposal.rationale}</p>
          ) : (
            <p className="proposal-card__rationale proposal-card__rationale--empty">
              No rationale attached.
            </p>
          )}

          {components.length > 0 ? (
            <ul className="proposal-card__comps">
              {components.map((c, i) => (
                <li key={i} className="proposal-card__comp">
                  <span className="num num--proposed">
                    {formatDecimal(
                      (c.qty as number | string | null | undefined) ?? null,
                    )}
                  </span>
                  <span>
                    {String(c.name ?? "component")}
                    {c.unit ? ` ${c.unit}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          {proposal.parse_error ? (
            <p className="field__error">{proposal.parse_error}</p>
          ) : null}

          {proposal.status === "rejected" && proposal.reject_reason ? (
            <p className="board-row__meta">
              Rejected: {proposal.reject_reason}
              {proposal.decided_at ? ` · ${proposal.decided_at}` : ""}
            </p>
          ) : null}
          {proposal.status === "accepted" && proposal.decided_at ? (
            <p className="board-row__meta">Accepted · {proposal.decided_at}</p>
          ) : null}

          {pending ? (
            rejectOpen ? (
              <div className="proposal-card__reject">
                <div className="board-line__checks">
                  {PROPOSAL_REJECT_REASONS.map((r) => (
                    <button
                      key={r}
                      type="button"
                      className="chip chip--danger"
                      disabled={busy}
                      onClick={() => {
                        if (r === "other") return;
                        onReject(proposal, r);
                        setRejectOpen(false);
                      }}
                    >
                      {r}
                    </button>
                  ))}
                </div>
                <div className="quick-add__row">
                  <input
                    className="field__input"
                    placeholder="Other reason"
                    value={otherNote}
                    onChange={(e) => setOtherNote(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={busy || !otherNote.trim()}
                    onClick={() => {
                      onReject(proposal, otherNote.trim());
                      setRejectOpen(false);
                    }}
                  >
                    Reject
                  </button>
                </div>
                <button
                  type="button"
                  className="link-back"
                  onClick={() => setRejectOpen(false)}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div className="board-line__checks">
                <button
                  type="button"
                  className="chip chip--ok"
                  disabled={busy || (conf === "low" && !open)}
                  title={
                    conf === "low" && !open
                      ? "Expand low-confidence proposals before accept"
                      : undefined
                  }
                  onClick={() => {
                    if (conf === "low" && !open) {
                      setOpen(true);
                      return;
                    }
                    onAccept(proposal);
                  }}
                >
                  Accept
                </button>
                <button
                  type="button"
                  className="chip chip--danger"
                  disabled={busy}
                  onClick={() => setRejectOpen(true)}
                >
                  Reject
                </button>
                {!canSwipeAccept ? (
                  <span className="board-row__meta">low conf — expand first</span>
                ) : null}
              </div>
            )
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

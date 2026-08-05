import { useState } from "react";
import type { ProposalOut } from "@/api/types";
import { PROPOSAL_REJECT_REASONS } from "@/contract";
import { formatDecimal } from "@/lib/decimal";
import {
  proposalTargetLabel,
  proposalTargetOf,
} from "@/lib/proposalTarget";

type Props = {
  proposal: ProposalOut;
  busy?: boolean;
  onAccept: (p: ProposalOut) => void;
  onReject: (p: ProposalOut, reason: string) => void;
  compact?: boolean;
  /** When true, render as inbox attention card (parse_error path) */
  inbox?: boolean;
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
  if (!p.rationale && !p.model) return "med";
  return "med";
}

function summaryLine(p: ProposalOut): string {
  const prop = p.proposal as Record<string, unknown>;
  if (typeof prop.note === "string" && prop.note) return prop.note;
  if (typeof prop.summary === "string" && prop.summary) return prop.summary;
  if (typeof prop.text === "string" && prop.text) return prop.text;
  if (p.kind === "parse_note") {
    const text =
      (p.context as { notes?: string; text?: string }).text ||
      (p.context as { notes?: string }).notes ||
      "";
    return text ? `Parse: ${text.slice(0, 80)}` : "Parse note";
  }
  if (p.parse_error) return "Parse failed";
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
  inbox,
}: Props) {
  const [open, setOpen] = useState(Boolean(inbox && proposal.parse_error));
  const [rejectOpen, setRejectOpen] = useState(false);
  const [otherNote, setOtherNote] = useState("");
  const conf = confidenceOf(proposal);
  const pending = proposal.status === "pending";
  const prop = proposal.proposal as Record<string, unknown>;
  const components = Array.isArray(prop.components)
    ? (prop.components as Array<Record<string, unknown>>)
    : [];
  const houseMade = Boolean(prop.house_made);
  const target = proposalTargetOf(proposal);
  const targetLabel = proposalTargetLabel(target);
  const isParseError = Boolean(proposal.parse_error?.trim());
  const canAccept =
    pending &&
    !isParseError &&
    proposal.accept_able !== false &&
    (conf !== "low" || open);

  return (
    <article
      className={[
        "proposal-card",
        pending ? "proposal-card--pending" : "",
        open ? "is-open" : "",
        isParseError ? "proposal-card--parse-error" : "",
        `proposal-card--target-${target}`,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        type="button"
        className="proposal-card__main"
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className={`board-row__badge board-row__badge--assist${
            isParseError ? " board-row__badge--error" : ""
          }`}
          aria-label={isParseError ? "parse error" : "assist"}
        >
          {isParseError ? "!" : "A"}
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
            {isParseError ? " · needs attention" : ""}
          </span>
          {!isParseError ? (
            <span
              className={`target-chip target-chip--${target}`}
              title="Accept target"
            >
              {targetLabel}
            </span>
          ) : null}
        </div>
        {houseMade ? (
          <span className="house-tag" title="house made">
            H
          </span>
        ) : null}
      </button>

      {open || !compact ? (
        <div className="proposal-card__body">
          {!isParseError ? (
            <div className={`target-banner target-banner--${target}`}>
              <span className="target-banner__k">Applies</span>
              <span className="target-banner__v">{targetLabel}</span>
            </div>
          ) : null}

          {proposal.rationale ? (
            <p className="proposal-card__rationale">{proposal.rationale}</p>
          ) : !isParseError ? (
            <p className="proposal-card__rationale proposal-card__rationale--empty">
              No rationale attached.
            </p>
          ) : null}

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

          {isParseError ? (
            <p className="field__error proposal-card__parse-error">
              {proposal.parse_error}
            </p>
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
                      className={`chip chip--danger${
                        r === "wrong scope" ? " chip--scope" : ""
                      }`}
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
                {!isParseError ? (
                  <button
                    type="button"
                    className="chip chip--ok"
                    disabled={busy || !canAccept}
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
                ) : (
                  <span className="board-row__meta" style={{ color: "var(--red)" }}>
                    no Accept — parse error
                  </span>
                )}
                <button
                  type="button"
                  className="chip chip--danger"
                  disabled={busy}
                  onClick={() => setRejectOpen(true)}
                >
                  Reject
                </button>
              </div>
            )
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

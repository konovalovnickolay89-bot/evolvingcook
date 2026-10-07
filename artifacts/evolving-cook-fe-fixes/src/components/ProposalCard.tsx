import { useState } from "react";
import type { ProposalOut } from "@/api/types";
import {
  PROPOSAL_REJECT_LABELS,
  PROPOSAL_REJECT_REASONS,
} from "@/contract";
import { formatDecimal } from "@/lib/decimal";
import {
  proposalContextLabel,
  proposalTargetLabel,
  proposalTargetOf,
  proposalTitle,
  rationaleDisplay,
  relativeAge,
  targetConfidenceOf,
} from "@/lib/proposalTarget";

type Props = {
  proposal: ProposalOut;
  busy?: boolean;
  onAccept: (p: ProposalOut) => void;
  onReject: (p: ProposalOut, reason: string) => void;
  /**
   * Collapsed-by-default (tap header to expand).
   * Inbox + board should pass compact — auto-open only parse_error.
   */
  compact?: boolean;
  /** Inbox surface: parse_error rewrite / dismiss */
  inbox?: boolean;
  /** Rewrite path: re-submit parse_note with new text (legitimate /assist/jobs use) */
  onRewrite?: (p: ProposalOut, newText: string) => void | Promise<void>;
};

export function ProposalCard({
  proposal,
  busy,
  onAccept,
  onReject,
  compact = true,
  inbox,
  onRewrite,
}: Props) {
  const isParseError = Boolean(proposal.parse_error?.trim());
  const [open, setOpen] = useState(Boolean(isParseError));
  const [rejectOpen, setRejectOpen] = useState(false);
  const [otherNote, setOtherNote] = useState("");
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [rewriteText, setRewriteText] = useState("");

  const conf = targetConfidenceOf(proposal);
  const pending = proposal.status === "pending";
  const prop = (proposal.proposal ?? {}) as Record<string, unknown>;
  const components = Array.isArray(prop.components)
    ? (prop.components as Array<Record<string, unknown>>)
    : [];
  const houseMade = Boolean(prop.house_made);
  const target = proposalTargetOf(proposal);
  const targetLabel = proposalTargetLabel(target);
  const title = proposalTitle(proposal);
  const ctxLabel = proposalContextLabel(proposal);
  const { main: rationaleMain, audit } = rationaleDisplay(
    proposal.rationale || "",
  );

  // Trust backend accept_able; low-conf never quick-accepts on collapsed card
  const backendOk = proposal.accept_able !== false && !isParseError;
  const showQuickAccept = pending && backendOk && conf === "high" && compact;
  const showExpandedAccept =
    pending && backendOk && (conf !== "high" || open || !compact);

  const bodyVisible = open || !compact || isParseError;

  const quotedNote =
    (typeof prop.note === "string" && prop.note) ||
    (typeof (proposal.context as { text?: string }).text === "string" &&
      (proposal.context as { text?: string }).text) ||
    (typeof (proposal.context as { notes?: string }).notes === "string" &&
      (proposal.context as { notes?: string }).notes) ||
    "";

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
        aria-expanded={bodyVisible}
      >
        <span
          className={`board-row__badge board-row__badge--assist${
            isParseError ? " board-row__badge--error" : ""
          }`}
          aria-label={isParseError ? "needs attention" : "assist"}
        >
          {isParseError ? "!" : "A"}
        </span>
        <div className="board-row__main">
          <span className="board-row__name proposal-card__title">{title}</span>
          <span className="board-row__meta">
            {[ctxLabel, relativeAge(proposal.created_at), !pending ? proposal.status : ""]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {!isParseError ? (
            <span className={`target-chip target-chip--${target}`}>
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

      {/* High-conf collapsed: Add / Pass without expanding */}
      {showQuickAccept && !open ? (
        <div className="proposal-card__quick">
          <button
            type="button"
            className="chip chip--ok"
            disabled={busy}
            onClick={() => onAccept(proposal)}
          >
            Add
          </button>
          <button
            type="button"
            className="chip chip--danger"
            disabled={busy}
            onClick={() => setRejectOpen(true)}
          >
            Pass
          </button>
        </div>
      ) : null}

      {rejectOpen && !bodyVisible ? (
        <RejectPanel
          busy={busy}
          otherNote={otherNote}
          setOtherNote={setOtherNote}
          onCancel={() => setRejectOpen(false)}
          onReject={(reason) => {
            onReject(proposal, reason);
            setRejectOpen(false);
          }}
        />
      ) : null}

      {bodyVisible ? (
        <div className="proposal-card__body">
          {isParseError ? (
            <>
              <p className="proposal-card__rationale">
                Couldn&apos;t read this note
              </p>
              {quotedNote ? (
                <blockquote className="proposal-card__quote">
                  {quotedNote}
                </blockquote>
              ) : null}
              {proposal.parse_error ? (
                <p className="board-row__meta">{proposal.parse_error}</p>
              ) : null}

              {rewriteOpen ? (
                <div className="note-edit">
                  <label className="field__label" htmlFor={`rw-${proposal.id}`}>
                    Rewrite note
                  </label>
                  <input
                    id={`rw-${proposal.id}`}
                    className="field__input"
                    value={rewriteText}
                    onChange={(e) => setRewriteText(e.target.value)}
                    placeholder="Type a clearer note"
                  />
                  <div className="board-line__checks">
                    <button
                      type="button"
                      className="chip chip--ok"
                      disabled={busy || !rewriteText.trim() || !onRewrite}
                      onClick={() => {
                        void onRewrite?.(proposal, rewriteText.trim());
                        setRewriteOpen(false);
                      }}
                    >
                      Resend
                    </button>
                    <button
                      type="button"
                      className="chip"
                      disabled={busy}
                      onClick={() => setRewriteOpen(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="board-line__checks">
                  <button
                    type="button"
                    className="chip chip--ok"
                    disabled={busy || !onRewrite}
                    onClick={() => {
                      setRewriteText(quotedNote);
                      setRewriteOpen(true);
                    }}
                  >
                    Rewrite
                  </button>
                  <button
                    type="button"
                    className="chip chip--danger"
                    disabled={busy}
                    onClick={() => onReject(proposal, "dismissed")}
                  >
                    Dismiss
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              <div className={`target-banner target-banner--${target}`}>
                <span className="target-banner__k">Applies</span>
                <span className="target-banner__v">{targetLabel}</span>
              </div>

              {conf === "low" ? (
                <p className="proposal-card__warn" role="note">
                  Low confidence — check the note before adding.
                </p>
              ) : null}

              {rationaleMain ? (
                <p className="proposal-card__rationale">{rationaleMain}</p>
              ) : (
                <p className="proposal-card__rationale proposal-card__rationale--empty">
                  No rationale attached.
                </p>
              )}
              {audit ? (
                <details className="proposal-card__audit">
                  <summary>Details</summary>
                  <p className="board-row__meta">{audit}</p>
                </details>
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

              {proposal.status === "rejected" && proposal.reject_reason ? (
                <p className="board-row__meta">
                  Rejected: {proposal.reject_reason}
                  {proposal.decided_at
                    ? ` · ${relativeAge(proposal.decided_at)}`
                    : ""}
                </p>
              ) : null}
              {proposal.status === "accepted" && proposal.decided_at ? (
                <p className="board-row__meta">
                  Accepted · {relativeAge(proposal.decided_at)}
                </p>
              ) : null}

              {pending ? (
                rejectOpen ? (
                  <RejectPanel
                    busy={busy}
                    otherNote={otherNote}
                    setOtherNote={setOtherNote}
                    onCancel={() => setRejectOpen(false)}
                    onReject={(reason) => {
                      onReject(proposal, reason);
                      setRejectOpen(false);
                    }}
                  />
                ) : (
                  <div className="board-line__checks">
                    {showExpandedAccept ? (
                      <button
                        type="button"
                        className="chip chip--ok"
                        disabled={busy}
                        onClick={() => onAccept(proposal)}
                      >
                        Accept
                      </button>
                    ) : null}
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
            </>
          )}
        </div>
      ) : null}
    </article>
  );
}

function RejectPanel({
  busy,
  otherNote,
  setOtherNote,
  onCancel,
  onReject,
}: {
  busy?: boolean;
  otherNote: string;
  setOtherNote: (s: string) => void;
  onCancel: () => void;
  onReject: (reason: string) => void;
}) {
  const [showOther, setShowOther] = useState(false);

  return (
    <div className="proposal-card__reject">
      {!showOther ? (
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
                if (r === "other") {
                  setShowOther(true);
                  return;
                }
                onReject(r);
              }}
            >
              {PROPOSAL_REJECT_LABELS[r]}
            </button>
          ))}
        </div>
      ) : (
        <div className="quick-add__row">
          <input
            className="field__input"
            placeholder="Something else…"
            value={otherNote}
            onChange={(e) => setOtherNote(e.target.value)}
            autoFocus
          />
          <button
            type="button"
            className="btn btn--ghost"
            disabled={busy || !otherNote.trim()}
            onClick={() => onReject(otherNote.trim())}
          >
            Reject
          </button>
        </div>
      )}
      <button type="button" className="link-back" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}

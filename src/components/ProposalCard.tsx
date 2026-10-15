import { useState } from "react";
import type { ProposalOut } from "@/api/types";
import { PROPOSAL_REJECT_LABELS, PROPOSAL_REJECT_REASONS } from "@/contract";
import { formatDecimal } from "@/lib/decimal";
import { todayServiceDate } from "@/lib/dates";
import {
  isQtyProposal,
  proposalContextLabel,
  proposalKindChip,
  proposalServiceDate,
  shortServiceDate,
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
  /** overlay → AcceptIn `{ proposal: overlay }` (e.g. chef-entered planned_qty) */
  onAccept: (p: ProposalOut, overlay?: Record<string, unknown>) => void;
  onReject: (p: ProposalOut, reason: string) => void;
  /**
   * Collapsed-by-default (tap header to expand).
   * Inbox + board pass compact — auto-open only parse_error.
   */
  compact?: boolean;
  /** Inbox surface: parse_error rewrite / dismiss */
  inbox?: boolean;
  /** Rewrite path: re-submit parse_note (legitimate /assist/jobs use) */
  onRewrite?: (p: ProposalOut, newText: string) => void | Promise<void>;
};

export function ProposalCard({
  proposal,
  busy,
  onAccept,
  onReject,
  compact = true,
  inbox: _inbox,
  onRewrite,
}: Props) {
  const isParseError = Boolean(proposal.parse_error?.trim());
  const [open, setOpen] = useState(Boolean(isParseError));
  const [rejectOpen, setRejectOpen] = useState(false);
  const [otherNote, setOtherNote] = useState("");
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const proposedQty = (proposal.proposal as Record<string, unknown> | null)
    ?.planned_qty;
  const [qtyText, setQtyText] = useState(
    proposedQty != null ? String(proposedQty) : "",
  );
  const [rewriteText, setRewriteText] = useState("");
  const isQty = !isParseError && isQtyProposal(proposal);
  const kindChip = isParseError ? null : proposalKindChip(proposal);

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
  const serviceDate = proposalServiceDate(proposal);
  const pastDay = serviceDate != null && serviceDate < todayServiceDate();
  const { main: rationaleMain, audit } = rationaleDisplay(
    proposal.rationale || "",
  );

  // Trust backend accept_able; low-conf never quick-accepts on collapsed card
  const backendOk = proposal.accept_able !== false && !isParseError;
  const showQuickAccept =
    pending && backendOk && conf === "high" && compact && !isQty;
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
            {[
              ctxLabel,
              serviceDate && serviceDate !== todayServiceDate()
                ? shortServiceDate(serviceDate)
                : "",
              relativeAge(proposal.created_at),
              !pending ? proposal.status : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {kindChip ? (
            <span className="target-chip target-chip--qty">
              {pastDay && pending ? `${kindChip} · past day` : kindChip}
            </span>
          ) : !isParseError ? (
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
      {showQuickAccept && !open && !rejectOpen ? (
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
                Couldn't read this note
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
          ) : isQty ? (
            <QtyBody
              proposal={proposal}
              busy={busy}
              pending={pending}
              pastDay={pastDay}
              qtyText={qtyText}
              setQtyText={setQtyText}
              rejectOpen={rejectOpen}
              setRejectOpen={setRejectOpen}
              otherNote={otherNote}
              setOtherNote={setOtherNote}
              onAccept={onAccept}
              onReject={onReject}
            />
          ) : (
            <>
              {!kindChip ? (
                <div className={`target-banner target-banner--${target}`}>
                  <span className="target-banner__k">Applies</span>
                  <span className="target-banner__v">{targetLabel}</span>
                </div>
              ) : null}

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

/** qty_draft / morning_qty: show the working, let the chef type the qty. */
function QtyBody({
  proposal,
  busy,
  pending,
  pastDay,
  qtyText,
  setQtyText,
  rejectOpen,
  setRejectOpen,
  otherNote,
  setOtherNote,
  onAccept,
  onReject,
}: {
  proposal: ProposalOut;
  busy?: boolean;
  pending: boolean;
  pastDay: boolean;
  qtyText: string;
  setQtyText: (s: string) => void;
  rejectOpen: boolean;
  setRejectOpen: (v: boolean) => void;
  otherNote: string;
  setOtherNote: (s: string) => void;
  onAccept: (p: ProposalOut, overlay?: Record<string, unknown>) => void;
  onReject: (p: ProposalOut, reason: string) => void;
}) {
  const prop = (proposal.proposal ?? {}) as Record<string, unknown>;
  const working = typeof prop.working === "string" ? prop.working : "";
  const unit = typeof prop.unit === "string" ? prop.unit : "";
  const clock = typeof prop.clock_time === "string" ? prop.clock_time : "";
  const proposed = prop.planned_qty;
  const n = Number(qtyText);
  const qtyOk = qtyText.trim() !== "" && Number.isFinite(n) && n >= 0;
  const inputId = `qty-${proposal.id}`;

  return (
    <div className="proposal-card__qty">
      <p className="proposal-card__rationale">
        {proposed != null
          ? `Suggested ${formatDecimal(proposed as number)}${unit ? ` ${unit}` : ""}`
          : "No suggestion yet — enter how many you need."}
        {clock ? ` · ready by ${clock}` : ""}
      </p>
      {working ? <p className="board-row__meta">{working}</p> : null}
      {pastDay ? (
        <p className="proposal-card__warn" role="note">
          This is for a past service day — probably safe to reject.
        </p>
      ) : null}

      {pending && !rejectOpen ? (
        <>
          <label className="field__label" htmlFor={inputId}>
            Planned qty{unit ? ` (${unit})` : ""}
          </label>
          <div className="quick-add__row">
            <input
              id={inputId}
              className="field__input"
              inputMode="decimal"
              value={qtyText}
              onChange={(e) => setQtyText(e.target.value)}
            />
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !qtyOk}
              onClick={() =>
                onAccept(proposal, {
                  planned_qty: n,
                  working:
                    proposed != null && Number(proposed) === n
                      ? working
                      : "chef set in inbox",
                })
              }
            >
              Set
            </button>
          </div>
          <div className="board-line__checks">
            <button
              type="button"
              className="chip chip--danger"
              disabled={busy}
              onClick={() => setRejectOpen(true)}
            >
              Reject
            </button>
          </div>
        </>
      ) : null}

      {pending && rejectOpen ? (
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

      {proposal.status === "accepted" ? (
        <p className="board-row__meta">
          Set to {formatDecimal(proposed as number | null)}
          {unit ? ` ${unit}` : ""}
          {proposal.decided_at ? ` · ${relativeAge(proposal.decided_at)}` : ""}
        </p>
      ) : null}
      {proposal.status === "rejected" ? (
        <p className="board-row__meta">
          Rejected{proposal.reject_reason ? `: ${proposal.reject_reason}` : ""}
          {proposal.decided_at ? ` · ${relativeAge(proposal.decided_at)}` : ""}
        </p>
      ) : null}
    </div>
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
              className={`chip chip--danger${r === "wrong scope" ? " chip--scope" : ""}`}
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

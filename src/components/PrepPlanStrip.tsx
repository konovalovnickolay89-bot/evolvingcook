import { useState } from "react";
import { formatDecimal } from "@/lib/decimal";
import type { PrepPlanPayload, PrepStep } from "@/lib/boardDepth";

type Props = {
  plan: PrepPlanPayload;
  busyId?: number | null;
  onAccept: (
    step: PrepStep,
    overlay?: { qty?: number; working?: string },
  ) => void;
  onPass: (step: PrepStep) => void;
};

/** F3 — guided banqueting prep_plan.steps */
export function PrepPlanStrip({ plan, busyId, onAccept, onPass }: Props) {
  const [adjustId, setAdjustId] = useState<number | null>(null);
  const [adjQty, setAdjQty] = useState("");

  const pending = plan.steps.filter((s) => s.status === "pending");
  const accepted = plan.steps.filter((s) => s.status === "accepted");
  if (!pending.length && !accepted.length) return null;

  const mep = pending.filter((s) => s.phase !== "day_of");
  const dayOf = pending.filter((s) => s.phase === "day_of");

  function renderStep(step: PrepStep) {
    const busy = busyId === step.proposal_id;
    const solid = step.status === "accepted";
    const adjusting = adjustId === step.proposal_id;

    return (
      <div
        key={step.proposal_id}
        className={`depth-card${solid ? " depth-card--solid" : " depth-card--dashed"}`}
      >
        <div className="depth-card__row">
          <div className="depth-card__main">
            {step.clock_time ? (
              <span className="depth-card__clock num">{step.clock_time}</span>
            ) : null}
            <span className="depth-card__title">{step.title}</span>
            {step.qty != null ? (
              <span className="depth-card__qty num">
                {formatDecimal(step.qty)}
                {step.unit ? ` ${step.unit}` : ""}
              </span>
            ) : null}
          </div>
        </div>
        {step.working ? (
          <p className="depth-card__working">{step.working}</p>
        ) : null}
        {step.watch_out ? (
          <p className="depth-card__watch">{step.watch_out}</p>
        ) : null}

        {!solid && adjusting ? (
          <div className="depth-card__adjust">
            <label className="field__label" htmlFor={`prep-${step.proposal_id}`}>
              Qty
            </label>
            <div className="quick-add__row">
              <input
                id={`prep-${step.proposal_id}`}
                className="field__input"
                inputMode="decimal"
                value={adjQty}
                onChange={(e) => setAdjQty(e.target.value)}
              />
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy || !adjQty.trim()}
                onClick={() => {
                  const n = Number(adjQty);
                  if (!Number.isFinite(n)) return;
                  onAccept(step, { qty: n, working: "chef adjusted" });
                  setAdjustId(null);
                }}
              >
                Save
              </button>
            </div>
            <button
              type="button"
              className="link-back"
              onClick={() => setAdjustId(null)}
            >
              Cancel
            </button>
          </div>
        ) : null}

        {!solid && !adjusting ? (
          <div className="depth-card__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !step.accept_able}
              onClick={() => onAccept(step)}
            >
              Looks right
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => {
                setAdjQty(step.qty != null ? String(step.qty) : "");
                setAdjustId(step.proposal_id);
              }}
            >
              Adjust
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => onPass(step)}
            >
              Pass
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <section className="depth-strip" aria-label="Prep plan">
      <div className="board__section-label">Prep plan</div>
      {mep.length > 0 ? (
        <>
          <p className="depth-strip__group">Mise en place — day before</p>
          <p className="depth-strip__hint">
            No clock here — work the order. Longest lead first.
          </p>
          {mep.map(renderStep)}
        </>
      ) : null}
      {dayOf.length > 0 ? (
        <>
          <p className="depth-strip__group">Day of — finish & hold</p>
          <p className="depth-strip__hint">
            Clock matters — times backwards-planned from service.
          </p>
          {dayOf.map(renderStep)}
        </>
      ) : null}
      {accepted.length > 0 ? (
        <>
          <p className="depth-strip__group">Accepted steps</p>
          {accepted.map(renderStep)}
        </>
      ) : null}
    </section>
  );
}

import { useState } from "react";
import { formatDecimal } from "@/lib/decimal";
import type { QtyDraftItem, QtyDraftPayload } from "@/lib/boardDepth";

type Props = {
  draft: QtyDraftPayload;
  busyId?: number | null;
  onAccept: (
    item: QtyDraftItem,
    overlay?: { planned_qty: number; working: string },
  ) => void;
  onPass: (item: QtyDraftItem) => void;
};

/** Counts strip — qty_draft / morning_qty items */
export function QtyDraftStrip({ draft, busyId, onAccept, onPass }: Props) {
  const [adjustId, setAdjustId] = useState<number | null>(null);
  const [adjQty, setAdjQty] = useState("");

  const pending = draft.items.filter((i) => i.status === "pending");
  const accepted = draft.items.filter((i) => i.status === "accepted");
  if (!pending.length && !accepted.length) return null;

  const mep = pending.filter((i) => i.phase !== "day_of");
  const dayOf = pending.filter((i) => i.phase === "day_of");

  function renderItem(item: QtyDraftItem) {
    const busy = busyId === item.proposal_id;
    const adjusting = adjustId === item.proposal_id;
    const solid = item.status === "accepted";

    return (
      <div
        key={item.proposal_id}
        className={`depth-card${solid ? " depth-card--solid" : " depth-card--dashed"}`}
      >
        <div className="depth-card__row">
          <div className="depth-card__main">
            {item.clock_time ? (
              <span className="depth-card__clock num">{item.clock_time}</span>
            ) : null}
            <span className="depth-card__title">{item.line_name}</span>
            <span className="depth-card__qty num">
              {formatDecimal(item.planned_qty)}
              {item.unit ? ` ${item.unit}` : ""}
            </span>
          </div>
        </div>
        {item.working ? (
          <p className="depth-card__working">{item.working}</p>
        ) : null}

        {!solid && adjusting ? (
          <div className="depth-card__adjust">
            <label className="field__label" htmlFor={`adj-${item.proposal_id}`}>
              Planned qty
            </label>
            <div className="quick-add__row">
              <input
                id={`adj-${item.proposal_id}`}
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
                  onAccept(item, {
                    planned_qty: n,
                    working: "chef adjusted",
                  });
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
              disabled={busy || !item.accept_able}
              onClick={() => onAccept(item)}
            >
              Looks right
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => {
                setAdjQty(
                  item.planned_qty != null ? String(item.planned_qty) : "",
                );
                setAdjustId(item.proposal_id);
              }}
            >
              Adjust
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => onPass(item)}
            >
              Pass
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <section className="depth-strip" aria-label="Quantity drafts">
      <div className="board__section-label">Qty draft</div>
      {mep.length > 0 ? (
        <>
          <p className="depth-strip__group">MEP · morning prep</p>
          {mep.map(renderItem)}
        </>
      ) : null}
      {dayOf.length > 0 ? (
        <>
          <p className="depth-strip__group">Day of · clocks</p>
          {dayOf.map(renderItem)}
        </>
      ) : null}
      {accepted.length > 0 ? (
        <>
          <p className="depth-strip__group">Accepted</p>
          {accepted.map(renderItem)}
        </>
      ) : null}
    </section>
  );
}

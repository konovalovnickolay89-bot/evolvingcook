import { formatDecimal } from "@/lib/decimal";
import type { OrderAssistCard as OrderAssistData } from "@/lib/boardDepth";

type Props = {
  card: OrderAssistData;
  busy?: boolean;
  onAccept: () => void;
  onPass: () => void;
};

/** F2 — top order_assist card on ordering boards */
export function OrderAssistCard({ card, busy, onAccept, onPass }: Props) {
  return (
    <div
      className={`order-assist${card.accept_able ? "" : " is-disabled"}`}
      data-proposal={card.proposal_id}
    >
      <div className="order-assist__head">
        <span className="order-assist__badge" aria-hidden>
          A
        </span>
        <span className="order-assist__kind">Order suggest</span>
      </div>
      {card.rationale ? (
        <p className="order-assist__rationale">{card.rationale}</p>
      ) : null}
      {card.lines.length > 0 ? (
        <ul className="order-assist__lines">
          {card.lines.map((ln, i) => (
            <li key={`${ln.item_id ?? ln.name}-${i}`}>
              <span className="order-assist__name">{ln.name}</span>
              {ln.packs != null ? (
                <span className="num order-assist__packs">
                  {formatDecimal(ln.packs)} pk
                </span>
              ) : null}
              {ln.why ? (
                <span className="order-assist__why">{ln.why}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="order-assist__actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={busy || !card.accept_able}
          onClick={onAccept}
        >
          Add to order
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={busy}
          onClick={onPass}
        >
          Pass
        </button>
      </div>
    </div>
  );
}

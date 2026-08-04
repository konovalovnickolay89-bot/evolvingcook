import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { batchDeliveryLines, getDelivery } from "@/api/purchasing";
import type { DeliveryLineIn, DeliveryLineOut } from "@/api/types";
import {
  DELIVERY_NOTE_STATES,
  type DeliveryNoteState,
} from "@/contract";
import { formatDecimal } from "@/lib/decimal";
import { EmptyState, LoadingState } from "@/components/AppShell";

type Props = {
  deliveryId: number;
  onBack: () => void;
};

const STATE_LABEL: Record<DeliveryNoteState, string> = {
  short: "Short",
  over: "Over",
  substituted: "Sub",
  rejected: "Reject",
};

type LineDraft = {
  received: string;
  note: DeliveryNoteState | "";
  text: string;
};

function normalizeNote(note: string): DeliveryNoteState | "" {
  const n = note.toLowerCase().trim();
  if ((DELIVERY_NOTE_STATES as readonly string[]).includes(n)) {
    return n as DeliveryNoteState;
  }
  return "";
}

function defaultDraft(line: DeliveryLineOut): LineDraft {
  return {
    received: line.packs_received != null ? String(line.packs_received) : "",
    note: normalizeNote(line.note || ""),
    text: line.note_text || "",
  };
}

export function DeliveryPage({ deliveryId, onBack }: Props) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<number, LineDraft>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const q = useQuery({
    queryKey: ["delivery", deliveryId],
    queryFn: ({ signal }) => getDelivery(deliveryId, signal),
    retry: 1,
  });

  const lines = q.data?.lines ?? [];

  const local = useMemo(() => {
    const map: Record<number, LineDraft> = {};
    for (const l of lines) {
      map[l.id] = draft[l.id] ?? defaultDraft(l);
    }
    return map;
  }, [lines, draft]);

  const saveMut = useMutation({
    mutationFn: async () => {
      if (!q.data) throw new Error("No delivery");
      const payload: DeliveryLineIn[] = q.data.lines.map((l) => {
        const d = local[l.id]!;
        const received =
          d.received.trim() === "" ? null : Number(d.received);
        return {
          supplier_item_id: l.supplier_item_id,
          packs_expected: l.packs_expected,
          packs_received: Number.isFinite(received as number)
            ? (received as number)
            : null,
          price: l.price,
          note: d.note || "",
          note_text: d.text || "",
        };
      });
      return batchDeliveryLines(deliveryId, { lines: payload });
    },
    onSuccess: (data) => {
      qc.setQueryData(["delivery", deliveryId], data);
      setDraft({});
      setSaved(true);
      setError(null);
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Save failed");
      setSaved(false);
    },
  });

  function patch(line: DeliveryLineOut, next: Partial<LineDraft>) {
    setSaved(false);
    setDraft((prev) => {
      const base = prev[line.id] ?? defaultDraft(line);
      return { ...prev, [line.id]: { ...base, ...next } };
    });
  }

  if (q.isLoading) return <LoadingState label="Loading delivery…" />;
  if (q.isError || !q.data) {
    return (
      <div className="stack">
        <button type="button" className="link-back" onClick={onBack}>
          ← Orders
        </button>
        <EmptyState
          title="Delivery unavailable"
          body={q.error instanceof Error ? q.error.message : "Not found"}
        />
      </div>
    );
  }

  const d = q.data;

  return (
    <div className="stack">
      <button type="button" className="link-back" onClick={onBack}>
        ← Orders
      </button>
      <div>
        <h2 className="page-title">Delivery</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          {d.supplier_name} · #{d.id} · {d.received_on} · {d.status}
        </p>
      </div>

      <div className="progress-strip">
        <span className="num num--planned">{d.line_count}</span>
        <span className="progress-strip__label">lines</span>
        <span className="num num--proposed">PO {d.purchase_order_id}</span>
      </div>

      {error ? <p className="field__error">{error}</p> : null}
      {saved ? (
        <p className="page-lead" style={{ color: "var(--green)", margin: 0 }}>
          Saved.
        </p>
      ) : null}

      <div className="board">
        <div className="board__section-label">
          expected · received · disposition
        </div>
        {lines.map((line) => {
          const loc = local[line.id]!;
          return (
            <div key={line.id} className="delivery-line">
              <div className="delivery-line__head">
                <span className="walk-row__name">{line.item_name}</span>
                <span className="walk-row__meta">
                  SI #{line.supplier_item_id}
                </span>
              </div>
              <div className="delivery-line__nums">
                <div className="section-card__stat">
                  <span className="num num--proposed">
                    {formatDecimal(line.packs_expected)}
                  </span>
                  <span className="section-card__stat-label">expect</span>
                </div>
                <div className="section-card__stat">
                  <input
                    className="field__input walk-row__input"
                    inputMode="decimal"
                    placeholder="Recv"
                    value={loc.received}
                    onChange={(e) =>
                      patch(line, { received: e.target.value })
                    }
                    aria-label={`Received packs ${line.item_name}`}
                  />
                  <span className="section-card__stat-label">recv</span>
                </div>
              </div>
              <div className="board-line__checks">
                {DELIVERY_NOTE_STATES.map((st) => (
                  <button
                    key={st}
                    type="button"
                    className={`chip${loc.note === st ? " is-on" : ""}${
                      st === "rejected" || st === "short" ? " chip--danger" : ""
                    }`}
                    onClick={() =>
                      patch(line, { note: loc.note === st ? "" : st })
                    }
                  >
                    {STATE_LABEL[st]}
                  </button>
                ))}
              </div>
              <input
                className="field__input"
                placeholder="Note (optional)"
                value={loc.text}
                maxLength={500}
                onChange={(e) => patch(line, { text: e.target.value })}
              />
            </div>
          );
        })}
      </div>

      <button
        type="button"
        className="btn btn--primary btn--block"
        disabled={saveMut.isPending}
        onClick={() => saveMut.mutate()}
      >
        {saveMut.isPending ? "Saving…" : "Save receipt"}
      </button>
    </div>
  );
}

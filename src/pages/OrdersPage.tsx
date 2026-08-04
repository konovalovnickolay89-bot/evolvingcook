import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createDelivery,
  getPurchaseOrder,
  sendPurchaseOrder,
} from "@/api/purchasing";
import type { POLineOut, PurchaseOrderOut } from "@/api/types";
import { formatDecimal } from "@/lib/decimal";
import { EmptyState, LoadingState } from "@/components/AppShell";
import { todayServiceDate } from "@/lib/dates";

type Props = {
  initialPoIds?: number[];
  onOpenDelivery?: (deliveryId: number) => void;
};

function packsClass(proposed: number | null, packs: number | null): string {
  if (packs === null) return "num num--planned";
  if (proposed !== null && packs !== proposed) return "num num--diverged";
  return "num num--planned";
}

function POLineRow({
  line,
  onOpen,
}: {
  line: POLineOut;
  onOpen: () => void;
}) {
  return (
    <button type="button" className="board-row" onClick={onOpen}>
      <span className="board-row__badge board-row__badge--produce">O</span>
      <div className="board-row__main">
        <span className="board-row__name">{line.item_name}</span>
        <span className="board-row__meta">
          {line.supplier_code || "—"} · {line.pack_description || "pack"}
        </span>
      </div>
      <div className="board-row__num-group" aria-label="proposed packs">
        <span className="board-row__num num--proposed" title="Proposed">
          {formatDecimal(line.proposed_packs)}
        </span>
        <span
          className={packsClass(line.proposed_packs ?? null, line.packs ?? null)}
          title="Planned packs"
        >
          {formatDecimal(line.packs)}
        </span>
        <span className="board-row__num num--actual" title="Shortfall">
          {formatDecimal(line.shortfall)}
        </span>
      </div>
    </button>
  );
}

function PODetail({
  line,
  onClose,
}: {
  line: POLineOut;
  onClose: () => void;
}) {
  return (
    <div className="board-line__actions">
      <button type="button" className="link-back" onClick={onClose}>
        Close breakdown
      </button>
      <div className="board-row-detail__grid">
        {(
          [
            ["Par", line.par],
            ["Counted", line.counted],
            ["On order", line.on_order],
            ["Shortfall", line.shortfall],
            ["Proposed packs", line.proposed_packs],
            ["Planned packs", line.packs],
            ["Pack qty", line.pack_qty],
            ["Price", line.price],
          ] as const
        ).map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <span className="board-row-detail__k">{k}</span>
            <span className="board-row-detail__v num">{formatDecimal(v)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function POCard({
  poId,
  onOpenDelivery,
}: {
  poId: number;
  onOpenDelivery?: (deliveryId: number) => void;
}) {
  const qc = useQueryClient();
  const [openLine, setOpenLine] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["po", poId],
    queryFn: ({ signal }) => getPurchaseOrder(poId, signal),
    retry: 1,
  });

  const sendMut = useMutation({
    mutationFn: () => sendPurchaseOrder(poId),
    onSuccess: (data) => {
      qc.setQueryData(["po", poId], data);
      setMsg("Sent");
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "Send failed"),
  });

  const deliveryMut = useMutation({
    mutationFn: () =>
      createDelivery(poId, {
        received_on: todayServiceDate(),
        notes: "",
        complete: false,
        lines: null,
      }),
    onSuccess: (data) => {
      setMsg(`Delivery #${data.id}`);
      onOpenDelivery?.(data.id);
    },
    onError: (e) =>
      setMsg(e instanceof Error ? e.message : "Delivery create failed"),
  });

  if (q.isLoading) return <LoadingState label={`PO #${poId}…`} />;
  if (q.isError || !q.data) {
    return (
      <EmptyState
        title={`PO #${poId}`}
        body={q.error instanceof Error ? q.error.message : "Not found"}
      />
    );
  }

  const po: PurchaseOrderOut = q.data;
  const lines = po.lines.slice();

  return (
    <div className="stack" style={{ gap: "var(--space-03)" }}>
      <div className="section-card" style={{ cursor: "default" }}>
        <div className="section-card__top">
          <span className="section-card__name">{po.supplier_name}</span>
          <span
            className={`status-chip status-chip--${po.status === "sent" ? "ok" : "muted"}`}
          >
            {po.status}
          </span>
        </div>
        <span className="section-card__meta">
          #{po.id} · order {po.order_date}
          {po.delivery_date ? ` · deliver ${po.delivery_date}` : ""}
          {" · "}
          {po.line_count} lines
        </span>
        <div className="walk-actions">
          <button
            type="button"
            className="btn btn--primary"
            disabled={sendMut.isPending || po.status === "sent"}
            onClick={() => sendMut.mutate()}
          >
            {po.status === "sent" ? "Sent" : "Send PO"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={deliveryMut.isPending}
            onClick={() => deliveryMut.mutate()}
          >
            Delivery receipt
          </button>
        </div>
        {msg ? (
          <p className="page-lead" style={{ margin: 0 }}>
            {msg}
          </p>
        ) : null}
      </div>

      <div className="board">
        <div className="board__section-label">
          proposed · planned · shortfall
        </div>
        {lines.map((line) => (
          <div key={line.id}>
            <POLineRow
              line={line}
              onOpen={() =>
                setOpenLine((id) => (id === line.id ? null : line.id))
              }
            />
            {openLine === line.id ? (
              <PODetail line={line} onClose={() => setOpenLine(null)} />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export function OrdersPage({ initialPoIds = [], onOpenDelivery }: Props) {
  const [poIds, setPoIds] = useState<number[]>(initialPoIds);
  const [input, setInput] = useState("");

  useEffect(() => {
    if (initialPoIds.length) setPoIds(initialPoIds);
  }, [initialPoIds]);

  const unique = useMemo(
    () => [...new Set(poIds)].filter((n) => Number.isFinite(n) && n > 0),
    [poIds],
  );

  return (
    <div className="stack">
      <div>
        <h2 className="page-title">Orders</h2>
        <p className="page-lead">
          Draft → send. Tap a line for par / counted / on-order / shortfall from
          the payload. Delivery receipt from each PO.
        </p>
      </div>

      {unique.length === 0 ? (
        <EmptyState
          title="No draft POs open"
          body="Submit a walk to build an order proposal, or open a PO by id."
        />
      ) : null}

      <form
        className="quick-add__form"
        onSubmit={(e) => {
          e.preventDefault();
          const n = Number(input.trim());
          if (!Number.isFinite(n) || n <= 0) return;
          setPoIds((ids) => [...ids, n]);
          setInput("");
        }}
      >
        <input
          className="field__input"
          inputMode="numeric"
          placeholder="PO id"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className="btn btn--ghost btn--block">
          Open PO
        </button>
      </form>

      {unique.map((id) => (
        <POCard key={id} poId={id} onOpenDelivery={onOpenDelivery} />
      ))}
    </div>
  );
}

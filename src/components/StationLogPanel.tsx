import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createStationLogLine,
  getStationLog,
  listStorageAreas,
  patchStationLogLine,
  suggestStationLog,
  type StationLogLineOut,
} from "@/api/stationLog";
import {
  LOG_ACTIONS,
  LOG_ACTION_LABELS,
  LOG_KIND_LABELS,
  LOG_KINDS,
  WALK_AREA_KEY,
  type LogAction,
  type LogKind,
} from "@/contract";

type Props = {
  serviceDate: string;
  section: string;
  compact?: boolean;
  onOpenWalk?: () => void;
};

export function StationLogPanel({
  serviceDate,
  section,
  compact,
  onOpenWalk,
}: Props) {
  const qc = useQueryClient();
  const key = ["station-log", serviceDate, section] as const;
  const [kind, setKind] = useState<LogKind>("mep");
  const [text, setText] = useState("");
  const [qty, setQty] = useState("");
  const [action, setAction] = useState<LogAction>("none");
  const [areaId, setAreaId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);

  const logQ = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => getStationLog(serviceDate, section, signal),
    retry: false,
  });

  const areasQ = useQuery({
    queryKey: ["storage-areas"],
    queryFn: ({ signal }) => listStorageAreas(signal),
    staleTime: 60_000,
  });

  const createMut = useMutation({
    mutationFn: () =>
      createStationLogLine(serviceDate, section, {
        kind,
        text: text.trim(),
        action,
        qty: qty.trim() === "" || !Number.isFinite(Number(qty))
          ? null
          : Number(qty),
        area_id: areaId === "" ? null : Number(areaId),
      }),
    onSuccess: async () => {
      setText("");
      setQty("");
      setError(null);
      await qc.invalidateQueries({ queryKey: key });
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Could not save");
    },
  });

  const suggestMut = useMutation({
    mutationFn: () => suggestStationLog(serviceDate, section),
    onSuccess: async () => {
      setError(null);
      await qc.invalidateQueries({ queryKey: key });
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Fill failed");
    },
  });

  async function setStatus(row: StationLogLineOut, status: "open" | "done") {
    setError(null);
    try {
      await patchStationLogLine(serviceDate, section, row.id, { status });
      await qc.invalidateQueries({ queryKey: key });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update");
    }
  }

  function openWalk(areaIdNum: number | null, areaName: string) {
    if (areaIdNum) {
      try {
        sessionStorage.setItem(
          WALK_AREA_KEY,
          JSON.stringify({ id: areaIdNum, name: areaName }),
        );
      } catch {
        /* ignore */
      }
    }
    onOpenWalk?.();
  }

  const byKind = logQ.data?.by_kind ?? {};
  const openCount = logQ.data?.open_count ?? 0;
  const areas = areasQ.data ?? [];

  const kindCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const k of LOG_KINDS) {
      const rows = byKind[k] ?? [];
      m[k] = rows.filter((r) => r.status === "open").length;
    }
    return m;
  }, [byKind]);

  return (
    <div className="station-log">
      <div className="station-log__head">
        <h3 className="station-log__title">Station log</h3>
        <span className="board-row__meta">
          {openCount} open
          {suggestMut.data?.provider
            ? ` · ${suggestMut.data.provider}`
            : ""}
        </span>
      </div>
      {!compact ? (
        <p className="page-lead" style={{ marginBottom: 0 }}>
          MEP, house prep, service, holding, leftovers, priority, expire soon.
          Link holding and leftovers to a real fridge or store.
        </p>
      ) : null}

      {logQ.isError ? (
        <p className="field__error">
          {logQ.error instanceof Error
            ? logQ.error.message
            : "Could not load log"}
        </p>
      ) : null}

      {/* Outstanding work reads first; the compose form lives below it. */}
      {LOG_KINDS.map((k) => {
        const rows = byKind[k] ?? [];
        if (compact && rows.length === 0) return null;
        if (!compact && k !== kind && rows.filter((r) => r.status === "open").length === 0) {
          return null;
        }
        const visible = compact
          ? rows
          : k === kind
            ? rows
            : rows.filter((r) => r.status === "open");
        if (visible.length === 0 && k !== kind) return null;
        return (
          <div key={k} className="station-log__group">
            <div className="board__section-label">{LOG_KIND_LABELS[k]}</div>
            {visible.length === 0 && k === kind ? (
              <p className="board-row__meta">Nothing here yet.</p>
            ) : null}
            {visible.map((row) => (
              <LogRow
                key={row.id}
                row={row}
                onDone={() => void setStatus(row, "done")}
                onReopen={() => void setStatus(row, "open")}
                onCheckWalk={
                  row.action === "check" && onOpenWalk
                    ? () => openWalk(row.area_id, row.area_name)
                    : undefined
                }
              />
            ))}
          </div>
        );
      })}

      <button
        type="button"
        className="btn btn--ghost btn--block"
        disabled={suggestMut.isPending}
        onClick={() => suggestMut.mutate()}
      >
        {suggestMut.isPending ? "Filling…" : "Fill from kitchen"}
      </button>

      <div className="kind-chips" role="tablist" aria-label="Log kind">
        {LOG_KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            className={`kind-chip${kind === k ? " is-on" : ""}`}
            onClick={() => setKind(k)}
          >
            {LOG_KIND_LABELS[k]}
            {kindCounts[k] ? ` ${kindCounts[k]}` : ""}
          </button>
        ))}
      </div>

      <form
        className="station-log__add"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          createMut.mutate();
        }}
      >
        <label className="field">
          <span className="field__label">What</span>
          <input
            className="field__input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. leftover pork walk-in"
          />
        </label>
        <div className="station-log__add-row">
          <label className="field">
            <span className="field__label">Qty</span>
            <input
              className="field__input"
              inputMode="decimal"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              placeholder="—"
            />
          </label>
          <label className="field">
            <span className="field__label">Do</span>
            <select
              className="field__input"
              value={action}
              onChange={(e) => setAction(e.target.value as LogAction)}
            >
              {LOG_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {LOG_ACTION_LABELS[a]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Store / fridge</span>
            <select
              className="field__input"
              value={areaId}
              onChange={(e) =>
                setAreaId(e.target.value === "" ? "" : Number(e.target.value))
              }
            >
              <option value="">—</option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          type="submit"
          className="btn btn--primary btn--block"
          disabled={createMut.isPending || !text.trim()}
        >
          {createMut.isPending ? "Saving…" : "Add to log"}
        </button>
      </form>

      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

function LogRow({
  row,
  onDone,
  onReopen,
  onCheckWalk,
}: {
  row: StationLogLineOut;
  onDone: () => void;
  onReopen: () => void;
  onCheckWalk?: () => void;
}) {
  const open = row.status === "open";
  const bits = [
    row.item_name,
    row.area_name,
    row.qty != null ? `${row.qty}${row.unit ? ` ${row.unit}` : ""}` : "",
    row.from_yesterday ? "from yesterday" : "",
    row.source === "suggest" ? "filled" : "",
    row.walk_count && row.walk_count.counted_qty != null
      ? `walk ${row.walk_count.counted_qty}`
      : "",
  ].filter(Boolean);
  return (
    <div className={`log-row${open ? "" : " log-row--done"}`}>
      <div className="log-row__body">
        <div className="log-row__text">{row.text}</div>
        {bits.length ? (
          <div className="board-row__meta">{bits.join(" · ")}</div>
        ) : null}
      </div>
      <div className="log-row__actions">
        {onCheckWalk ? (
          <button type="button" className="btn btn--ghost" onClick={onCheckWalk}>
            Walk
          </button>
        ) : null}
        {open ? (
          <button type="button" className="btn btn--ghost" onClick={onDone}>
            Done
          </button>
        ) : (
          <button type="button" className="btn btn--ghost" onClick={onReopen}>
            Open
          </button>
        )}
      </div>
    </div>
  );
}

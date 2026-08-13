import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  batchWalkLines,
  lockWalk,
  orderProposal,
  startWalk,
  submitWalk,
} from "@/api/walks";
import { ApiError, refreshToken } from "@/api/client";
import type { OrderProposalOut, WalkLineBatchIn } from "@/api/types";
import {
  clearWalkLocal,
  getActiveWalkMeta,
  getLocalWalkLines,
  markWalkSynced,
  saveLocalLine,
  seedWalkLocal,
  setWalkSyncError,
  type LocalWalkLine,
  type LocalWalkMeta,
} from "@/db";
import { formatDecimal } from "@/lib/decimal";
import { EmptyState, LoadingState } from "@/components/AppShell";
import { WALK_AREA_KEY } from "@/contract";

type WalkAreaHint = { id: number; name: string };

function peekWalkArea(): WalkAreaHint | null {
  try {
    const raw = sessionStorage.getItem(WALK_AREA_KEY);
    if (!raw) return null;
    const asNum = Number(raw);
    if (Number.isFinite(asNum) && asNum > 0) {
      return { id: asNum, name: "" };
    }
    const o = JSON.parse(raw) as { id?: number; name?: string };
    if (o && typeof o.id === "number" && o.id > 0) {
      return { id: o.id, name: o.name ?? "" };
    }
  } catch {
    /* ignore */
  }
  return null;
}

type Props = {
  onOpenOrders: (poIds: number[]) => void;
};

export function WalkPage({ onOpenOrders }: Props) {
  const [booting, setBooting] = useState(true);
  const [meta, setMeta] = useState<LocalWalkMeta | null>(null);
  const [lines, setLines] = useState<LocalWalkLine[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncPrompt, setSyncPrompt] = useState(false);
  const [proposal, setProposal] = useState<OrderProposalOut | null>(null);

  const reloadLocal = useCallback(async (walkId: number) => {
    const rows = await getLocalWalkLines(walkId);
    setLines(rows);
    const m = await getActiveWalkMeta();
    if (m && m.walkId === walkId) setMeta(m);
  }, []);

  useEffect(() => {
    void (async () => {
      const m = await getActiveWalkMeta();
      if (m) {
        setMeta(m);
        setLines(await getLocalWalkLines(m.walkId));
      }
      setBooting(false);
    })();
  }, []);

  const startMut = useMutation({
    mutationFn: () => {
      const hint = peekWalkArea();
      return startWalk({
        kind: "order",
        area_id: hint?.id ?? null,
        notes: "",
      });
    },
    retry: false,
    onSuccess: async (walk) => {
      try {
        sessionStorage.removeItem(WALK_AREA_KEY);
      } catch {
        /* ignore */
      }
      await seedWalkLocal(walk);
      setMeta(await getActiveWalkMeta() ?? null);
      setLines(await getLocalWalkLines(walk.id));
      setError(null);
      setProposal(null);
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Could not start walk");
    },
  });

  const progress = useMemo(() => {
    let counted = 0;
    let skipped = 0;
    for (const l of lines) {
      if (l.skipped) skipped += 1;
      else if (l.countedQty !== null) counted += 1;
    }
    const total = lines.length;
    const remaining = Math.max(0, total - counted - skipped);
    return { counted, skipped, remaining, total };
  }, [lines]);

  async function setCount(line: LocalWalkLine, raw: string) {
    // blank field → clear count (not skip)
    if (raw.trim() === "") {
      await saveLocalLine({
        key: line.key,
        countedQty: null,
        skipped: false,
      });
      await reloadLocal(line.walkId);
      return;
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    await saveLocalLine({
      key: line.key,
      countedQty: n,
      skipped: false,
      countedUnit: line.countedUnit || line.itemBaseUnit,
    });
    await reloadLocal(line.walkId);
  }

  async function setSkip(line: LocalWalkLine) {
    await saveLocalLine({
      key: line.key,
      skipped: true,
      countedQty: null,
    });
    await reloadLocal(line.walkId);
  }

  async function setZero(line: LocalWalkLine) {
    await saveLocalLine({
      key: line.key,
      skipped: false,
      countedQty: 0,
      countedUnit: line.countedUnit || line.itemBaseUnit,
    });
    await reloadLocal(line.walkId);
  }

  async function syncBatch(opts?: { reauth?: boolean }): Promise<boolean> {
    if (!meta) return false;
    setSyncing(true);
    setError(null);
    try {
      if (opts?.reauth) {
        try {
          await refreshToken();
        } catch {
          // still try batch — may already be valid
        }
      }
      const dirty = (await getLocalWalkLines(meta.walkId)).filter((l) => l.dirty);
      if (dirty.length === 0) {
        await markWalkSynced(meta.walkId, JSON.parse(meta.snapshotJson));
        setSyncing(false);
        return true;
      }
      const payload: WalkLineBatchIn[] = dirty.map((l) => ({
        item_id: l.itemId,
        area_id: l.areaId,
        line_id: l.lineId,
        counted_qty: l.skipped ? null : l.countedQty,
        counted_unit: l.countedUnit || l.itemBaseUnit,
        skipped: l.skipped,
        note: l.note || "",
      }));
      const walk = await batchWalkLines(meta.walkId, { lines: payload });
      await seedWalkLocal(walk);
      // re-apply was cleared — dirty already written to server
      await markWalkSynced(meta.walkId, walk);
      setMeta(await getActiveWalkMeta() ?? null);
      setLines(await getLocalWalkLines(meta.walkId));
      setSyncing(false);
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && !opts?.reauth) {
        setSyncing(false);
        return syncBatch({ reauth: true });
      }
      const msg = e instanceof Error ? e.message : "Sync failed";
      await setWalkSyncError(meta.walkId, msg);
      setError(msg);
      setMeta(await getActiveWalkMeta() ?? null);
      setSyncing(false);
      return false;
    }
  }

  async function onSubmitWalk() {
    if (!meta) return;
    setSyncPrompt(true);
    const ok = await syncBatch();
    if (!ok) return;
    try {
      const walk = await submitWalk(meta.walkId);
      await seedWalkLocal(walk);
      await markWalkSynced(meta.walkId, walk);
      setMeta(await getActiveWalkMeta() ?? null);
      // order proposal
      const prop = await orderProposal(meta.walkId);
      setProposal(prop);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        try {
          await refreshToken();
          const walk = await submitWalk(meta.walkId);
          await seedWalkLocal(walk);
          setMeta(await getActiveWalkMeta() ?? null);
          const prop = await orderProposal(meta.walkId);
          setProposal(prop);
          return;
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Submit failed");
          return;
        }
      }
      setError(e instanceof Error ? e.message : "Submit failed");
    }
  }

  if (booting) return <LoadingState label="Loading walk…" />;

  if (!meta) {
    const hint = peekWalkArea();
    return (
      <div className="stack">
        <div>
          <h2 className="page-title">Walk</h2>
          <p className="page-lead">
            Full stock walk offline after start. Skip ≠ 0. Sync only when you
            say so — local counts never discarded on error.
          </p>
        </div>
        {error ? <p className="field__error">{error}</p> : null}
        <button
          type="button"
          className="btn btn--primary btn--block"
          disabled={startMut.isPending}
          onClick={() => startMut.mutate()}
        >
          {startMut.isPending ? "Starting…" : "Start walk"}
        </button>
        <p className="page-lead" style={{ fontSize: "var(--fs-label)" }}>
          {hint
            ? `Starts ${hint.name || "the store/fridge"} from the station log.`
            : "Starts the full route (all areas). Check on a log row jumps here with that fridge."}
        </p>
      </div>
    );
  }

  const active = lines.find((l) => l.key === activeKey) ?? null;

  return (
    <div className="stack walk-page">
      <div>
        <h2 className="page-title">Walk #{meta.walkId}</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          {meta.status}
          {meta.areaName ? ` · ${meta.areaName}` : " · full route"}
          {meta.pendingSync ? " · unsynced local" : ""}
        </p>
      </div>

      <div className="progress-strip" aria-live="polite">
        <span className="num num--actual">{progress.counted}</span>
        <span className="progress-strip__label">counted</span>
        <span className="num num--proposed">{progress.skipped}</span>
        <span className="progress-strip__label">skipped</span>
        <span className="num num--planned">{progress.remaining}</span>
        <span className="progress-strip__label">left</span>
        <span className="num">{progress.total}</span>
        <span className="progress-strip__label">total</span>
      </div>

      {error ? <p className="field__error">{error}</p> : null}
      {meta.lastSyncError ? (
        <p className="field__error">
          Last sync: {meta.lastSyncError} — local data kept.
        </p>
      ) : null}

      {syncPrompt ? (
        <div className="banner banner--update" role="status">
          <span>Sync before iOS evicts storage — submit keeps a server copy.</span>
        </div>
      ) : null}

      <div className="walk-actions">
        <button
          type="button"
          className="btn btn--ghost"
          disabled={syncing}
          onClick={() => void syncBatch()}
        >
          {syncing ? "Syncing…" : "Sync now"}
        </button>
        <button
          type="button"
          className="btn btn--primary"
          disabled={syncing || meta.status === "locked"}
          onClick={() => void onSubmitWalk()}
        >
          Submit walk
        </button>
      </div>

      {proposal ? (
        <div className="stack">
          <EmptyState
            title="Order proposal ready"
            body={`${proposal.purchase_orders.length} draft PO(s) from this walk.`}
            action={
              <button
                type="button"
                className="btn btn--primary btn--block"
                onClick={() => onOpenOrders(proposal.purchase_order_ids)}
              >
                Review orders
              </button>
            }
          />
        </div>
      ) : null}

      <div className="board">
        <div className="board__section-label">
          walk_order · never re-sorted
        </div>
        {lines.map((line) => {
          const isActive = line.key === activeKey;
          const stateCls = line.skipped
            ? "walk-row--skipped"
            : line.countedQty !== null
              ? "walk-row--counted"
              : "";
          return (
            <div key={line.key} className={`walk-row ${stateCls}`}>
              <button
                type="button"
                className="walk-row__main"
                onClick={() =>
                  setActiveKey(isActive ? null : line.key)
                }
              >
                <span className="walk-row__name">{line.itemName}</span>
                <span className="walk-row__meta">
                  {line.areaName ?? "—"} · {line.itemBaseUnit}
                  {line.dirty ? " · local" : ""}
                </span>
                <span className="walk-row__val num">
                  {line.skipped
                    ? "SKIP"
                    : line.countedQty === null
                      ? "—"
                      : formatDecimal(line.countedQty)}
                </span>
              </button>
              {isActive ? (
                <div className="walk-row__pad">
                  <div className="walk-row__keys">
                    <input
                      className="field__input walk-row__input"
                      inputMode="decimal"
                      placeholder="Count"
                      defaultValue={
                        line.skipped || line.countedQty === null
                          ? ""
                          : String(line.countedQty)
                      }
                      key={`${line.key}-${line.updatedAt}`}
                      onBlur={(e) => void setCount(line, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          void setCount(
                            line,
                            (e.target as HTMLInputElement).value,
                          );
                        }
                      }}
                    />
                    <button
                      type="button"
                      className="chip"
                      onClick={() => void setZero(line)}
                    >
                      0
                    </button>
                    <button
                      type="button"
                      className="chip chip--skip"
                      onClick={() => void setSkip(line)}
                    >
                      Skip
                    </button>
                  </div>
                  <div className="board-row-detail__grid" style={{ marginTop: 8 }}>
                    <span className="board-row-detail__k">Par</span>
                    <span className="board-row-detail__v num">
                      {formatDecimal(line.par)}
                    </span>
                    <span className="board-row-detail__k">On order</span>
                    <span className="board-row-detail__v num">
                      {formatDecimal(line.onOrder)}
                    </span>
                    <span className="board-row-detail__k">Shortfall</span>
                    <span className="board-row-detail__v num">
                      {formatDecimal(line.shortfall)}
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {meta.status !== "locked" ? (
        <button
          type="button"
          className="btn btn--ghost btn--block"
          onClick={async () => {
            if (!meta) return;
            try {
              await lockWalk(meta.walkId);
              await clearWalkLocal(meta.walkId);
              setMeta(null);
              setLines([]);
              setProposal(null);
            } catch (e) {
              setError(e instanceof Error ? e.message : "Lock failed");
            }
          }}
        >
          Lock & clear local walk
        </button>
      ) : null}
    </div>
  );
}

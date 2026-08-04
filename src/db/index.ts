import Dexie, { type Table } from "dexie";
import type { WalkLineOut, WalkOut } from "@/api/types";

/**
 * Offline store — NEVER cleared on 401 or token eviction.
 * Walk counting is fully local mid-walk; batch submit is the retry mechanism.
 */

export type MetaRow = {
  key: string;
  value: string;
};

/** Local edit for one walk line — skip and 0 are distinct */
export type LocalWalkLine = {
  /** `${walkId}:${lineId}` */
  key: string;
  walkId: number;
  lineId: number;
  itemId: number;
  areaId: number | null;
  areaName: string | null;
  sortOrder: number;
  itemName: string;
  itemBaseUnit: string;
  /** null = blank (not counted); 0 = empty shelf; number = count */
  countedQty: number | null;
  countedUnit: string;
  /** true = skipped — never coerce with countedQty 0 */
  skipped: boolean;
  note: string;
  dirty: boolean;
  updatedAt: number;
  /** snapshot fields for display */
  par: number | null;
  onOrder: number | null;
  shortfall: number | null;
};

export type LocalWalkMeta = {
  walkId: number;
  kind: string;
  status: string;
  areaId: number | null;
  areaName: string | null;
  startedAt: string;
  lineCount: number;
  pendingSync: boolean;
  lastSyncError: string | null;
  lastSyncAt: number | null;
  snapshotJson: string;
};

class EvolvingCookDB extends Dexie {
  meta!: Table<MetaRow, string>;
  walkMeta!: Table<LocalWalkMeta, number>;
  walkLines!: Table<LocalWalkLine, string>;

  constructor() {
    super("evolving-cook");
    this.version(1).stores({
      meta: "key",
      walkEntries: "++id, itemId, updatedAt",
    });
    this.version(2)
      .stores({
        meta: "key",
        walkMeta: "walkId",
        walkLines: "key, walkId, sortOrder, dirty, updatedAt",
      })
      .upgrade(async (tx) => {
        await tx.table("walkEntries").clear().catch(() => undefined);
      });
  }
}

export const db = new EvolvingCookDB();

export async function ensureDbOpen(): Promise<void> {
  if (!db.isOpen()) {
    await db.open();
  }
}

export async function seedWalkLocal(walk: WalkOut): Promise<void> {
  await ensureDbOpen();
  const lines = walk.lines
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);

  await db.transaction("rw", db.walkMeta, db.walkLines, async () => {
    await db.walkMeta.put({
      walkId: walk.id,
      kind: walk.kind,
      status: walk.status,
      areaId: walk.area_id ?? null,
      areaName: walk.area_name ?? null,
      startedAt: walk.started_at,
      lineCount: walk.line_count,
      pendingSync: false,
      lastSyncError: null,
      lastSyncAt: null,
      snapshotJson: JSON.stringify(walk),
    });

    const existing = await db.walkLines.where("walkId").equals(walk.id).toArray();
    const dirtyMap = new Map(
      existing.filter((e) => e.dirty).map((e) => [e.key, e]),
    );

    await db.walkLines.where("walkId").equals(walk.id).delete();

    const rows: LocalWalkLine[] = lines.map((l) => {
      const key = `${walk.id}:${l.id}`;
      const prev = dirtyMap.get(key);
      if (prev) return prev;
      return fromServerLine(walk.id, l);
    });
    await db.walkLines.bulkPut(rows);
  });
}

export function fromServerLine(
  walkId: number,
  l: WalkLineOut,
): LocalWalkLine {
  return {
    key: `${walkId}:${l.id}`,
    walkId,
    lineId: l.id,
    itemId: l.item_id,
    areaId: l.area_id ?? null,
    areaName: l.area_name ?? null,
    sortOrder: l.sort_order,
    itemName: l.item_name,
    itemBaseUnit: l.item_base_unit || "ea",
    countedQty: l.counted_qty ?? null,
    countedUnit: l.counted_unit || l.item_base_unit || "ea",
    skipped: l.skipped,
    note: l.note || "",
    dirty: false,
    updatedAt: Date.now(),
    par: l.par ?? null,
    onOrder: l.on_order ?? null,
    shortfall: l.shortfall ?? null,
  };
}

export async function saveLocalLine(
  patch: Partial<LocalWalkLine> & { key: string },
): Promise<void> {
  await ensureDbOpen();
  const cur = await db.walkLines.get(patch.key);
  if (!cur) return;
  await db.walkLines.put({
    ...cur,
    ...patch,
    dirty: true,
    updatedAt: Date.now(),
  });
  await db.walkMeta.update(cur.walkId, { pendingSync: true });
}

export async function getLocalWalkLines(
  walkId: number,
): Promise<LocalWalkLine[]> {
  await ensureDbOpen();
  const rows = await db.walkLines.where("walkId").equals(walkId).toArray();
  return rows.sort((a, b) => a.sortOrder - b.sortOrder || a.lineId - b.lineId);
}

export async function getActiveWalkMeta(): Promise<LocalWalkMeta | undefined> {
  await ensureDbOpen();
  const all = await db.walkMeta.toArray();
  return all
    .slice()
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt))[0];
}

export async function clearWalkLocal(walkId: number): Promise<void> {
  await ensureDbOpen();
  await db.transaction("rw", db.walkMeta, db.walkLines, async () => {
    await db.walkLines.where("walkId").equals(walkId).delete();
    await db.walkMeta.delete(walkId);
  });
}

export async function markWalkSynced(
  walkId: number,
  walk: WalkOut,
): Promise<void> {
  await ensureDbOpen();
  await db.walkMeta.update(walkId, {
    status: walk.status,
    pendingSync: false,
    lastSyncError: null,
    lastSyncAt: Date.now(),
    snapshotJson: JSON.stringify(walk),
    lineCount: walk.line_count,
  });
  const dirty = await db.walkLines
    .where("walkId")
    .equals(walkId)
    .filter((l) => l.dirty)
    .toArray();
  for (const row of dirty) {
    await db.walkLines.update(row.key, { dirty: false });
  }
}

export async function setWalkSyncError(
  walkId: number,
  message: string,
): Promise<void> {
  await ensureDbOpen();
  await db.walkMeta.update(walkId, {
    pendingSync: true,
    lastSyncError: message,
  });
}

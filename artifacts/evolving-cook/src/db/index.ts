import Dexie, { type Table } from "dexie";

/**
 * Offline store skeleton.
 * Walk/count data lives here — NEVER cleared on 401 or token eviction.
 * Phase 2 will write walk lines; Phase 0 only opens the DB so eviction
 * of localStorage auth cannot cascade into schema drops.
 */

export type MetaRow = {
  key: string;
  value: string;
};

export type WalkEntryDraft = {
  id?: number;
  itemId: string;
  /** blank = skipped; explicit 0 = empty shelf — never coerce */
  quantity: number | null;
  skipped: boolean;
  unit: string;
  updatedAt: number;
};

class EvolvingCookDB extends Dexie {
  meta!: Table<MetaRow, string>;
  walkEntries!: Table<WalkEntryDraft, number>;

  constructor() {
    super("evolving-cook");
    this.version(1).stores({
      meta: "key",
      walkEntries: "++id, itemId, updatedAt",
    });
  }
}

export const db = new EvolvingCookDB();

export async function ensureDbOpen(): Promise<void> {
  if (!db.isOpen()) {
    await db.open();
  }
}

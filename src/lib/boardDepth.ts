/**
 * Loose parsers for BoardOut.qty_draft / prep_plan / order_assist
 * (OpenAPI marks them as free-form objects).
 */

export type StockStatus =
  | "in_stock"
  | "running_low"
  | "on_order"
  | "unknown";

export type OrderAssistLine = {
  item_id?: number;
  name: string;
  packs?: number | null;
  why?: string;
};

export type OrderAssistCard = {
  proposal_id: number;
  kind: string;
  target?: string;
  rationale: string;
  lines: OrderAssistLine[];
  accept_able: boolean;
};

export type QtyDraftItem = {
  proposal_id: number;
  kind: string;
  status: string;
  accept_able: boolean;
  line_id?: number;
  line_name: string;
  planned_qty: number | null;
  unit: string;
  working: string;
  phase: string;
  order_index: number;
  clock_time: string | null;
  target: string;
};

export type QtyDraftPayload = {
  section?: string;
  service_date?: string;
  items: QtyDraftItem[];
};

export type PrepStep = {
  proposal_id: number;
  status: string;
  accept_able: boolean;
  title: string;
  phase: string;
  order_index: number;
  clock_time: string | null;
  qty: number | null;
  unit: string;
  working: string;
  watch_out: string | null;
  target: string;
};

export type PrepPlanPayload = {
  steps: PrepStep[];
};

function asRecord(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function numOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

export function parseOrderAssist(raw: unknown): OrderAssistCard | null {
  const o = asRecord(raw);
  if (!o) return null;
  const id = numOrNull(o.proposal_id);
  if (id == null) return null;
  const linesRaw = Array.isArray(o.lines) ? o.lines : [];
  const lines: OrderAssistLine[] = [];
  for (const row of linesRaw) {
    const r = asRecord(row);
    if (!r) continue;
    const name = str(r.name) || str(r.item_name);
    if (!name) continue;
    const itemId = numOrNull(r.item_id);
    lines.push({
      ...(itemId != null ? { item_id: itemId } : {}),
      name,
      packs: numOrNull(r.packs),
      why: str(r.why) || undefined,
    });
  }

  return {
    proposal_id: id,
    kind: str(o.kind, "order_suggest"),
    target: str(o.target) || undefined,
    rationale: str(o.rationale),
    lines,
    accept_able: o.accept_able !== false,
  };
}

export function parseQtyDraft(raw: unknown): QtyDraftPayload | null {
  const o = asRecord(raw);
  if (!o) return null;
  const itemsRaw = Array.isArray(o.items) ? o.items : [];
  const items: QtyDraftItem[] = [];
  itemsRaw.forEach((row, i) => {
    const r = asRecord(row);
    if (!r) return;
    const pid = numOrNull(r.proposal_id);
    if (pid == null) return;
    const lineId = numOrNull(r.line_id);
    const orderIndex = numOrNull(r.order_index);
    items.push({
      proposal_id: pid,
      kind: str(r.kind, "qty_draft"),
      status: str(r.status, "pending"),
      accept_able: r.accept_able !== false,
      ...(lineId != null ? { line_id: lineId } : {}),
      line_name: str(r.line_name, "Line"),
      planned_qty: numOrNull(r.planned_qty),
      unit: str(r.unit),
      working: str(r.working),
      phase: str(r.phase, "mep"),
      order_index: orderIndex != null ? orderIndex : i,
      clock_time:
        typeof r.clock_time === "string" && r.clock_time
          ? r.clock_time
          : null,
      target: str(r.target, "planned_qty"),
    });
  });
  items.sort((a, b) => a.order_index - b.order_index);

  if (!items.length) return null;
  return {
    section: str(o.section) || undefined,
    service_date: str(o.service_date) || undefined,
    items,
  };
}

export function parsePrepPlan(raw: unknown): PrepPlanPayload | null {
  const o = asRecord(raw);
  if (!o) return null;
  const stepsRaw = Array.isArray(o.steps) ? o.steps : [];
  const steps: PrepStep[] = [];
  stepsRaw.forEach((row, i) => {
    const r = asRecord(row);
    if (!r) return;
    const pid = numOrNull(r.proposal_id);
    if (pid == null) return;
    const orderIndex = numOrNull(r.order_index);
    steps.push({
      proposal_id: pid,
      status: str(r.status, "pending"),
      accept_able: r.accept_able !== false,
      title: str(r.title, "Prep step"),
      phase: str(r.phase, "mep"),
      order_index: orderIndex != null ? orderIndex : i,
      clock_time:
        typeof r.clock_time === "string" && r.clock_time
          ? r.clock_time
          : null,
      qty: numOrNull(r.qty),
      unit: str(r.unit),
      working: str(r.working),
      watch_out: str(r.watch_out) || null,
      target: str(r.target, "prep_step"),
    });
  });
  steps.sort((a, b) => a.order_index - b.order_index);

  if (!steps.length) return null;
  return { steps };
}

export function stockDotClass(status: string | null | undefined): string {
  switch (status) {
    case "in_stock":
      return "stock-dot stock-dot--in";
    case "running_low":
      return "stock-dot stock-dot--low";
    case "on_order":
      return "stock-dot stock-dot--order";
    default:
      return "stock-dot stock-dot--unknown";
  }
}

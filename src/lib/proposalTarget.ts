import type { ProposalOut } from "@/api/types";
import { todayServiceDate } from "@/lib/dates";
import {
  PROPOSAL_TARGET_LABELS,
  SECTION_LABELS,
  type ProposalTargetKey,
} from "@/contract";

/**
 * Accept target (D14 / 0.1.14):
 * Prefer top-level ProposalOut.target; fall back to proposal/context bags.
 * line → today only | template → every day on this dish | item → permanent
 */
export function proposalTargetOf(
  p: ProposalOut | Record<string, unknown>,
): ProposalTargetKey {
  const top =
    "target" in p && p.target != null && p.target !== ""
      ? String(p.target)
      : null;
  const prop =
    "proposal" in p && p.proposal && typeof p.proposal === "object"
      ? (p.proposal as Record<string, unknown>)
      : (p as Record<string, unknown>);
  const ctx =
    "context" in p && p.context && typeof p.context === "object"
      ? (p.context as Record<string, unknown>)
      : {};

  const raw =
    top ??
    prop.target ??
    prop.scope ??
    prop.apply_to ??
    prop.accept_target ??
    ctx.target ??
    ctx.scope ??
    ctx.apply_to;

  const s = String(raw ?? "")
    .toLowerCase()
    .trim();

  if (
    s === "item" ||
    s === "permanent" ||
    s === "item_notes" ||
    s.includes("permanent")
  ) {
    return "item";
  }
  if (
    s === "template" ||
    s === "template_notes" ||
    s === "dish" ||
    s.includes("every day") ||
    s.includes("template")
  ) {
    return "template";
  }
  return "line";
}

export function proposalTargetLabel(key: ProposalTargetKey): string {
  return PROPOSAL_TARGET_LABELS[key];
}

/** Backend 0.1.14: ProposalOut.target_confidence ∈ high | medium | low */
export type TargetConfidence = "high" | "med" | "low";

export function targetConfidenceOf(p: ProposalOut): TargetConfidence {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  // Prefer top-level field (0.1.14); bag nested confidence only as fallback
  const raw = p.target_confidence ?? prop.target_confidence ?? prop.confidence;
  const s = String(raw ?? "")
    .toLowerCase()
    .trim();
  if (s === "high" || s === "h") return "high";
  if (s === "medium" || s === "med" || s === "m") return "med";
  if (s === "low" || s === "l") return "low";
  const n = typeof raw === "number" ? raw : Number(raw);
  if (Number.isFinite(n)) {
    if (n >= 0.75) return "high";
    if (n >= 0.45) return "med";
    return "low";
  }
  return "med";
}

/** qty_draft / morning_qty — sets planned_qty on a board line, not a note. */
export function isQtyProposal(p: ProposalOut): boolean {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  return (
    prop.target === "planned_qty" ||
    p.kind === "qty_draft" ||
    p.kind === "morning_qty"
  );
}

/** Service date the proposal belongs to (context.service_date), if any. */
export function proposalServiceDate(p: ProposalOut): string | null {
  const c = (p.context ?? {}) as Record<string, unknown>;
  return typeof c.service_date === "string" && c.service_date
    ? c.service_date
    : null;
}

/** Targets that only touch one service day's board (lines / POs for that date). */
const DAY_TARGETS = new Set([
  "line",
  "planned_qty",
  "prep_step",
  "order_packs",
  "component_fill",
  "new_line",
]);
const DAY_KINDS = new Set([
  "qty_draft",
  "morning_qty",
  "prep_plan",
  "order_suggest",
  "menu_completeness",
]);

/**
 * True only for proposals that belong to a service day that has passed.
 * Permanent (item) / every-day (template) notes and unreadable notes outlive
 * the day they were written on — never "past", even with a service_date.
 */
export function isPastDayProposal(p: ProposalOut): boolean {
  if (p.parse_error?.trim()) return false;
  const d = proposalServiceDate(p);
  if (d == null || d >= todayServiceDate()) return false;
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  const t = String(p.target ?? prop.target ?? "")
    .toLowerCase()
    .trim();
  return DAY_TARGETS.has(t) || (!t && DAY_KINDS.has(p.kind));
}

/** order_packs rows: [{ name, packs, item_id, why }] */
export function orderLinesOf(p: ProposalOut): Array<Record<string, unknown>> {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  return Array.isArray(prop.lines)
    ? (prop.lines as unknown[]).filter(
        (r): r is Record<string, unknown> => !!r && typeof r === "object",
      )
    : [];
}

/** "Tue 6 Oct" for a YYYY-MM-DD service date. */
export function shortServiceDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  if (!Number.isFinite(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/** D15 targets that aren't note scopes: chip label + title prefix. */
const KIND_LABELS: Record<string, { chip: string; prefix: string }> = {
  planned_qty: { chip: "qty draft", prefix: "Qty" },
  prep_step: { chip: "prep step", prefix: "Prep" },
  component_fill: { chip: "ingredients", prefix: "Ingredients" },
  order_packs: { chip: "order", prefix: "Order" },
  new_line: { chip: "new dish line", prefix: "New line" },
};

function kindLabelOf(p: ProposalOut): { chip: string; prefix: string } | null {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  const t = typeof prop.target === "string" ? prop.target : "";
  if (KIND_LABELS[t]) return KIND_LABELS[t]!;
  if (p.kind === "qty_draft" || p.kind === "morning_qty")
    return KIND_LABELS.planned_qty!;
  if (p.kind === "prep_plan") return KIND_LABELS.prep_step!;
  return null;
}

/** Chip for non-note proposals (qty / prep / ingredients …); null → note scope chip. */
export function proposalKindChip(p: ProposalOut): string | null {
  return kindLabelOf(p)?.chip ?? null;
}

/** Human title: note — never kind enum, never raw note slice prefix */
export function proposalTitle(p: ProposalOut): string {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  const ctx = (p.context ?? {}) as Record<string, unknown>;
  const kind = kindLabelOf(p);
  if (kind && !p.parse_error?.trim()) {
    const str = (v: unknown) => (typeof v === "string" ? v.trim() : "");
    const lines = orderLinesOf(p);
    const what =
      str(prop.title) ||
      str(prop.line_name) ||
      str(prop.name) ||
      str(ctx.line_name) ||
      str(ctx.dish) ||
      (lines.length
        ? `${lines.length} item${lines.length === 1 ? "" : "s"}`
        : "") ||
      str(prop.supplier_name);
    return what ? `${kind.prefix} · ${what}` : kind.prefix;
  }
  const note =
    (typeof prop.note === "string" && prop.note.trim()) ||
    (typeof prop.summary === "string" && prop.summary.trim()) ||
    (typeof prop.text === "string" && prop.text.trim()) ||
    "";
  const target = proposalTargetLabel(proposalTargetOf(p));
  if (p.parse_error?.trim()) {
    return "Couldn't read this note";
  }
  if (note) return note;
  return `Proposal · ${target}`;
}

/** Context chip: resolved names from enriched context */
export function proposalContextLabel(p: ProposalOut): string {
  const c = (p.context ?? {}) as Record<string, unknown>;
  if (typeof c.line_name === "string" && c.line_name.trim()) return c.line_name;
  if (typeof c.item_name === "string" && c.item_name.trim()) return c.item_name;
  if (typeof c.template_name === "string" && c.template_name.trim())
    return c.template_name;
  if (typeof c.section === "string" && c.section.trim()) {
    return (SECTION_LABELS as Record<string, string>)[c.section] ?? c.section;
  }
  return "";
}

/** Rationale before first " | " audit segment */
export function rationaleDisplay(full: string): {
  main: string;
  audit: string | null;
} {
  const idx = full.indexOf(" | ");
  if (idx === -1) return { main: full, audit: null };
  return {
    main: full.slice(0, idx).trim(),
    audit: full.slice(idx + 3).trim() || null,
  };
}

export function relativeAge(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/** Normalize board line.pending_proposal → ProposalOut for cards. */
export function coercePendingProposal(
  raw: unknown,
  lineId: number,
): ProposalOut | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.id !== "number") return null;

  const status = typeof o.status === "string" ? o.status : "pending";
  if (status !== "pending" && status !== "") return null;

  const parseError = typeof o.parse_error === "string" ? o.parse_error : "";
  // D14: parse_error is inbox-only
  if (parseError.trim()) return null;

  const context: { [key: string]: unknown } =
    o.context && typeof o.context === "object"
      ? { ...(o.context as object) }
      : { line_id: lineId };

  const proposal: { [key: string]: unknown } =
    o.proposal && typeof o.proposal === "object"
      ? { ...(o.proposal as object) }
      : {};

  // Promote nested target/confidence if top-level missing (older payloads)
  const target =
    typeof o.target === "string"
      ? o.target
      : typeof proposal.target === "string"
        ? (proposal.target as string)
        : null;
  const targetConfidence =
    typeof o.target_confidence === "string"
      ? o.target_confidence
      : typeof proposal.target_confidence === "string"
        ? (proposal.target_confidence as string)
        : null;

  return {
    id: o.id,
    kind: typeof o.kind === "string" ? o.kind : "parse_note",
    context,
    proposal,
    target,
    target_confidence: targetConfidence,
    rationale: typeof o.rationale === "string" ? o.rationale : "",
    model: typeof o.model === "string" ? o.model : "",
    status: "pending",
    decided_at:
      typeof o.decided_at === "string" || o.decided_at === null
        ? (o.decided_at as string | null)
        : null,
    reject_reason: typeof o.reject_reason === "string" ? o.reject_reason : "",
    task_id:
      typeof o.task_id === "string" || o.task_id === null
        ? (o.task_id as string | null)
        : null,
    job_id:
      typeof o.job_id === "number" || o.job_id === null
        ? (o.job_id as number | null)
        : null,
    parse_error: "",
    accept_able: typeof o.accept_able === "boolean" ? o.accept_able : true,
    created_at:
      typeof o.created_at === "string"
        ? o.created_at
        : new Date().toISOString(),
    updated_at:
      typeof o.updated_at === "string"
        ? o.updated_at
        : new Date().toISOString(),
  };
}

import type { ProposalOut } from "@/api/types";
import {
  PROPOSAL_TARGET_LABELS,
  type ProposalTargetKey,
} from "@/contract";

/**
 * Accept target from proposal payload (D14):
 * line → today only | template → every day on this dish | item → permanent
 */
export function proposalTargetOf(
  p: ProposalOut | Record<string, unknown>,
): ProposalTargetKey {
  const prop =
    "proposal" in p && p.proposal && typeof p.proposal === "object"
      ? (p.proposal as Record<string, unknown>)
      : (p as Record<string, unknown>);
  const ctx =
    "context" in p && p.context && typeof p.context === "object"
      ? (p.context as Record<string, unknown>)
      : {};

  const raw =
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

/** Backend: proposal.target_confidence ∈ high | medium | low */
export type TargetConfidence = "high" | "med" | "low";

export function targetConfidenceOf(p: ProposalOut): TargetConfidence {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
  const raw = prop.target_confidence ?? prop.confidence;
  const s = String(raw ?? "")
    .toLowerCase()
    .trim();
  if (s === "high" || s === "h") return "high";
  if (s === "medium" || s === "med" || s === "m") return "med";
  if (s === "low" || s === "l") return "low";
  // numeric 0–1 rare fallback
  const n = typeof raw === "number" ? raw : Number(raw);
  if (Number.isFinite(n)) {
    if (n >= 0.75) return "high";
    if (n >= 0.45) return "med";
    return "low";
  }
  // default medium friction when unknown
  return "med";
}

/** Human title: note + target — never kind enum, never raw note slice prefix */
export function proposalTitle(p: ProposalOut): string {
  const prop = (p.proposal ?? {}) as Record<string, unknown>;
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
  if (typeof c.section === "string" && c.section.trim()) return c.section;
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

  const parseError =
    typeof o.parse_error === "string" ? o.parse_error : "";
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

  return {
    id: o.id,
    kind: typeof o.kind === "string" ? o.kind : "parse_note",
    context,
    proposal,
    rationale: typeof o.rationale === "string" ? o.rationale : "",
    model: typeof o.model === "string" ? o.model : "",
    status: "pending",
    decided_at:
      typeof o.decided_at === "string" || o.decided_at === null
        ? (o.decided_at as string | null)
        : null,
    reject_reason:
      typeof o.reject_reason === "string" ? o.reject_reason : "",
    task_id:
      typeof o.task_id === "string" || o.task_id === null
        ? (o.task_id as string | null)
        : null,
    job_id:
      typeof o.job_id === "number" || o.job_id === null
        ? (o.job_id as number | null)
        : null,
    parse_error: "",
    accept_able:
      typeof o.accept_able === "boolean" ? o.accept_able : true,
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

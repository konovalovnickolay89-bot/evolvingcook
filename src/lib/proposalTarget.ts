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
  // D14: parse_error is inbox-only — never render Accept path on the row
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

/** Typed context only for parse_note jobs (D14). */
export function parseNoteContext(input: {
  text: string;
  line_id: number;
  section: string;
}): { text: string; line_id: number; section: string } {
  return {
    text: input.text,
    line_id: input.line_id,
    section: input.section,
  };
}

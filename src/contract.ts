/**
 * Contract version this build was generated against.
 * Regenerate src/api/schema.d.ts and bump this when openapi.json moves.
 */
export const EXPECTED_CONTRACT_VERSION = "0.1.18" as const;

export const API_BASE = "https://api.apidiscoverysolution.uk/api/v1" as const;

export const ALL_SECTIONS = [
  "skybar",
  "breakfast_buffet",
  "a_la_carte",
  "banquet_buffet",
  "banqueting",
  "canteen",
] as const;

export type SectionId = (typeof ALL_SECTIONS)[number];

export const SECTION_LABELS: Record<SectionId, string> = {
  skybar: "Skybar",
  breakfast_buffet: "Breakfast buffet",
  a_la_carte: "À la carte",
  banquet_buffet: "Banquet buffet",
  banqueting: "Banqueting",
  canteen: "Canteen",
};

/** One-line purpose for a station running chef. */
export const SECTION_PURPOSE: Record<SectionId, string> = {
  skybar: "Check the menu, 86 a dish, see what to order.",
  breakfast_buffet: "Replenish against par.",
  a_la_carte: "Check the menu, 86 a dish, see ingredients / what to order.",
  banquet_buffet: "Covers in, scale produce, then the prep list.",
  banqueting: "Covers in, scale produce, then the prep list.",
  canteen: "Produce list with counts.",
};

export const LAST_STATION_KEY = "evolvingcook.lastStation";
export const WALK_AREA_KEY = "evolvingcook.walkAreaId";

export const LOG_KINDS = [
  "mep",
  "house_prep",
  "service",
  "holding",
  "leftover",
  "cook_priority",
  "expire_soon",
] as const;

export type LogKind = (typeof LOG_KINDS)[number];

export const LOG_KIND_LABELS: Record<LogKind, string> = {
  mep: "Mise en place",
  house_prep: "House prep",
  service: "Service",
  holding: "Holding",
  leftover: "Leftovers",
  cook_priority: "Priority",
  expire_soon: "Expire soon",
};

export const LOG_ACTIONS = ["none", "check", "order", "prep", "hold"] as const;
export type LogAction = (typeof LOG_ACTIONS)[number];

export const LOG_ACTION_LABELS: Record<LogAction, string> = {
  none: "Note",
  check: "Check",
  order: "Order",
  prep: "Prep",
  hold: "Hold",
};

/** Service-face row mode hint (D7) */
export const SECTION_SERVICE_MODE: Record<
  SectionId,
  "check" | "replenish" | "produce" | "waves"
> = {
  skybar: "check",
  breakfast_buffet: "replenish",
  a_la_carte: "check",
  canteen: "produce",
  banqueting: "waves",
  banquet_buffet: "waves",
};

export type SectionMode = "counts" | "ordering";

/** D15 — chef-facing mode labels (pill colours in CSS) */
export const SECTION_MODE_LABELS: Record<SectionMode, string> = {
  counts: "Counts",
  ordering: "Ordering",
};

export function defaultQuickAddMode(section: string): string {
  if (section === "breakfast_buffet") return "replenish";
  if (section === "canteen") return "produce";
  return "check";
}

export const DELIVERY_NOTE_STATES = [
  "short",
  "over",
  "substituted",
  "rejected",
] as const;

export type DeliveryNoteState = (typeof DELIVERY_NOTE_STATES)[number];

/** API reject reason values (sent on RejectIn.reason) */
export const PROPOSAL_REJECT_REASONS = [
  "wrong scope",
  "wrong qty",
  "not needed",
  "wrong item",
  "other",
] as const;

/** Plain labels for reject chips (presentation) */
export const PROPOSAL_REJECT_LABELS: Record<
  (typeof PROPOSAL_REJECT_REASONS)[number],
  string
> = {
  "wrong scope": "Wrong scope",
  "wrong qty": "Wrong amount",
  "not needed": "Not needed",
  "wrong item": "Wrong item",
  other: "Something else…",
};

/** D14 accept targets: line | template | item */
export const PROPOSAL_TARGET_LABELS = {
  line: "today only",
  template: "every day on this dish",
  item: "permanent",
} as const;

export type ProposalTargetKey = keyof typeof PROPOSAL_TARGET_LABELS;

export const WALK_AREA_LABELS = [
  "Walk-in fridge",
  "Walk-in freezer",
  "Dry store",
  "Pastry",
  "Butcher",
  "Veg prep",
  "Skybar cellar",
  "Banquet hold",
] as const;

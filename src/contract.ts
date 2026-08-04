/**
 * Contract version this build was generated against.
 * Regenerate src/api/schema.d.ts and bump this when openapi.json moves.
 */
export const EXPECTED_CONTRACT_VERSION = "0.1.12" as const;

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

/** Reject reason chips for assist proposals (§10a) */
export const PROPOSAL_REJECT_REASONS = [
  "wrong qty",
  "not needed",
  "wrong item",
  "other",
] as const;

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

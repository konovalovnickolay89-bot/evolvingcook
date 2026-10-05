import { ALL_SECTIONS, type SectionId } from "@/contract";
import { isAllowedServiceDate } from "@/lib/dates";

/** Board face — mirrors BoardPage's "mep" | "service" toggle. */
export type StationFace = "mep" | "service";

/** Where the chef was last working: station + service day + board face. */
export type StationContext = {
  serviceDate: string;
  section: SectionId;
  face: StationFace;
};

const KEY = "evolvingcook.stationContext";

/**
 * Last working context, or null when none is stored or the stored day is
 * no longer today/yesterday — a stale day must never be resumed silently.
 */
export function readStationContext(): StationContext | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const o = JSON.parse(raw) as Partial<StationContext>;
    if (
      typeof o.serviceDate === "string" &&
      isAllowedServiceDate(o.serviceDate) &&
      typeof o.section === "string" &&
      (ALL_SECTIONS as readonly string[]).includes(o.section)
    ) {
      return {
        serviceDate: o.serviceDate,
        section: o.section as SectionId,
        face: o.face === "service" ? "service" : "mep",
      };
    }
  } catch {
    /* ignore */
  }
  return null;
}

/**
 * Record arrival on a station surface (log or board). Keeps the remembered
 * face when it is the same station and day; a different station starts on
 * Prep again.
 */
export function rememberStation(serviceDate: string, section: string): void {
  if (!(ALL_SECTIONS as readonly string[]).includes(section)) return;
  const prev = readStationContext();
  const face: StationFace =
    prev && prev.serviceDate === serviceDate && prev.section === section
      ? prev.face
      : "mep";
  write({ serviceDate, section: section as SectionId, face });
}

/** Record the face the chef toggled to on the board. */
export function rememberFace(
  serviceDate: string,
  section: string,
  face: StationFace,
): void {
  if (!(ALL_SECTIONS as readonly string[]).includes(section)) return;
  write({ serviceDate, section: section as SectionId, face });
}

function write(ctx: StationContext): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(ctx));
  } catch {
    /* ignore */
  }
}

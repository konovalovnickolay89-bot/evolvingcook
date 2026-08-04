import type { ProductionLineOut } from "@/api/types";
import { formatDecimal, parseDecimal } from "./decimal";
import type { CheckState, LineMode } from "@/components/BoardRow";

export function normalizeMode(mode: string): LineMode {
  const m = mode.toLowerCase();
  if (m === "produce" || m === "production") return "produce";
  if (m === "replenish" || m === "replenishment") return "replenish";
  return "check";
}

export function isEightySix(status: string): boolean {
  const s = status.toLowerCase().replace(/[_\s-]/g, "");
  return s === "eightysix" || s === "86" || s === "oos";
}

export function checkStateFromLine(line: ProductionLineOut): CheckState {
  if (isEightySix(line.status)) return "86";
  if (line.ticked || line.status.toLowerCase() === "ready") return "confirm";
  return "present";
}

export function lineMeta(line: ProductionLineOut): string {
  const parts: string[] = [];
  if (line.category) parts.push(line.category);
  if (line.source && line.source !== "template") parts.push(line.source);
  // Shared prep indicator (D6) — only lounge flag on contract today
  if (line.supports_lounge) parts.push("covers: lounge");
  return parts.join(" · ");
}

export function lineBreakdown(
  line: ProductionLineOut,
): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [
    { label: "Mode", value: line.mode },
    { label: "Status", value: line.status },
    { label: "Unit", value: line.unit || "—" },
    { label: "Proposed", value: formatDecimal(line.proposed_qty) },
    { label: "Planned", value: formatDecimal(line.planned_qty) },
    { label: "Actual", value: formatDecimal(line.actual_qty) },
    { label: "Par", value: formatDecimal(line.par_level) },
    { label: "Source", value: line.source || "—" },
  ];
  if (line.notes) {
    rows.push({ label: "Notes", value: line.notes });
  }
  if (line.supports_lounge) {
    rows.push({ label: "Covers", value: "lounge" });
  }
  if (line.components.length) {
    const done = line.components.filter((c) => c.done).length;
    rows.push({
      label: "Components",
      value: `${done}/${line.components.length}`,
    });
  }
  return rows;
}

export function produceNums(line: ProductionLineOut) {
  const proposed = parseDecimal(line.proposed_qty);
  const planned = parseDecimal(line.planned_qty);
  const actual = parseDecimal(line.actual_qty);
  let progress: number | null = null;
  if (planned != null && planned > 0 && actual != null) {
    progress = actual / planned;
  }
  return { proposed, planned, actual, progress };
}

/** Display-only mapping — no top-up math; third slot is planned from API. */
export function replenishNums(line: ProductionLineOut) {
  return {
    par: parseDecimal(line.par_level),
    onHand: parseDecimal(line.actual_qty),
    topUp: parseDecimal(line.planned_qty),
  };
}

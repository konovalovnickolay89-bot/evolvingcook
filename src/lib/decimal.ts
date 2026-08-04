/**
 * Contract 0.1.6+: Decimal qty fields are JSON numbers (or null).
 * 0.1.5 typed them as strings — still accept both for display-only parse.
 */
export function parseDecimal(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatDecimal(value: string | number | null | undefined): string {
  const n = parseDecimal(value);
  if (n === null) return "—";
  if (Number.isInteger(n)) return String(n);
  return String(n);
}

/** Local calendar date YYYY-MM-DD for service day (kitchen timezone = device). */
export function todayServiceDate(): string {
  return formatServiceDate(new Date());
}

export function yesterdayServiceDate(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatServiceDate(d);
}

export function formatServiceDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function shiftServiceDate(iso: string, deltaDays: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y!, (m ?? 1) - 1, d ?? 1);
  dt.setDate(dt.getDate() + deltaDays);
  return formatServiceDate(dt);
}

/** Phone only allows today or yesterday. */
export function isAllowedServiceDate(iso: string): boolean {
  return iso === todayServiceDate() || iso === yesterdayServiceDate();
}

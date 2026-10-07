/**
 * Auth token in localStorage only — no cookies.
 * Token eviction (iOS ~7d) must NEVER clear Dexie/local operational data.
 */

const TOKEN_KEY = "ec.access_token";
const EXPIRES_AT_KEY = "ec.token_expires_at";

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getTokenExpiresAt(): number | null {
  try {
    const raw = localStorage.getItem(EXPIRES_AT_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

export function setAccessToken(token: string, expiresInSeconds: number): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(
      EXPIRES_AT_KEY,
      String(Date.now() + expiresInSeconds * 1000),
    );
  } catch {
    // Quota / private mode — surface via caller if needed
  }
}

/** Clear auth only. Never touches Dexie or walk/board payload. */
export function clearAccessToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EXPIRES_AT_KEY);
  } catch {
    // ignore
  }
}

export function isTokenPresent(): boolean {
  return Boolean(getAccessToken());
}

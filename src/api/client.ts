import { API_BASE } from "@/contract";
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/tokenStorage";
import type { ErrorOut, LoginIn, TokenOut, VersionOut } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: ErrorOut | null;

  constructor(status: number, message: string, body: ErrorOut | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code ?? `http_${status}`;
    this.body = body;
  }
}

type RequestOpts = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** When false, skip Authorization header (login). Default true. */
  auth?: boolean;
  signal?: AbortSignal;
};

/**
 * Browser → API direct. Bearer only. No credentials: 'include'.
 * Never discards local operational data on 401.
 */
export async function apiRequest<T>(
  path: string,
  opts: RequestOpts = {},
): Promise<T> {
  const { method = "GET", body, auth = true, signal } = opts;
  const headers = new Headers();
  headers.set("Accept", "application/json");

  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  if (auth) {
    const token = getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    // Explicit — Safari ITP / CORS: no cookies
    credentials: "omit",
    mode: "cors",
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const errBody =
      data && typeof data === "object" && data !== null && "detail" in data
        ? (data as ErrorOut)
        : null;
    throw new ApiError(
      res.status,
      errBody?.detail ?? `Request failed (${res.status})`,
      errBody,
    );
  }

  return data as T;
}

export async function fetchVersion(signal?: AbortSignal): Promise<VersionOut> {
  return apiRequest<VersionOut>("/version", { auth: false, signal });
}

export async function login(
  credentials: LoginIn,
  signal?: AbortSignal,
): Promise<TokenOut> {
  const token = await apiRequest<TokenOut>("/auth/login", {
    method: "POST",
    body: credentials,
    auth: false,
    signal,
  });
  setAccessToken(token.access_token, token.expires_in);
  return token;
}

export async function refreshToken(
  signal?: AbortSignal,
): Promise<TokenOut> {
  const current = getAccessToken();
  const token = await apiRequest<TokenOut>("/auth/refresh", {
    method: "POST",
    body: current ? { access_token: current } : null,
    auth: true,
    signal,
  });
  setAccessToken(token.access_token, token.expires_in);
  return token;
}

/** Auth-only clear. Does not touch walk/board IndexedDB. */
export function logoutAuthOnly(): void {
  clearAccessToken();
}

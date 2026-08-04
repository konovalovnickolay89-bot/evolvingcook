import { apiRequest } from "./client";
import type {
  BatchLinesIn,
  OrderProposalOut,
  StartWalkIn,
  WalkOut,
} from "./types";

export function startWalk(
  body: StartWalkIn,
  signal?: AbortSignal,
): Promise<WalkOut> {
  return apiRequest<WalkOut>("/walks/start", {
    method: "POST",
    body,
    signal,
  });
}

export function getWalk(
  walkId: number,
  signal?: AbortSignal,
): Promise<WalkOut> {
  return apiRequest<WalkOut>(`/walks/${walkId}`, { signal });
}

export function batchWalkLines(
  walkId: number,
  body: BatchLinesIn,
  signal?: AbortSignal,
): Promise<WalkOut> {
  return apiRequest<WalkOut>(`/walks/${walkId}/lines/batch`, {
    method: "POST",
    body,
    signal,
  });
}

export function submitWalk(
  walkId: number,
  signal?: AbortSignal,
): Promise<WalkOut> {
  return apiRequest<WalkOut>(`/walks/${walkId}/submit`, {
    method: "POST",
    body: null,
    signal,
  });
}

export function lockWalk(
  walkId: number,
  signal?: AbortSignal,
): Promise<WalkOut> {
  return apiRequest<WalkOut>(`/walks/${walkId}/lock`, {
    method: "POST",
    body: null,
    signal,
  });
}

export function orderProposal(
  walkId: number,
  signal?: AbortSignal,
): Promise<OrderProposalOut> {
  return apiRequest<OrderProposalOut>(`/walks/${walkId}/order-proposal`, {
    method: "POST",
    body: null,
    signal,
  });
}

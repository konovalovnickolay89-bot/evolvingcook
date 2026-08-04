import { apiRequest } from "./client";
import type {
  ExplodeIn,
  JobCreateIn,
  JobOut,
  ProposalOut,
  RejectIn,
} from "./types";

export type ListProposalsParams = {
  status?: string | null;
  kind?: string | null;
  limit?: number;
};

export function listProposals(
  params: ListProposalsParams = {},
  signal?: AbortSignal,
): Promise<ProposalOut[]> {
  const q = new URLSearchParams();
  if (params.status != null && params.status !== "") {
    q.set("status", params.status);
  }
  if (params.kind != null && params.kind !== "") {
    q.set("kind", params.kind);
  }
  if (params.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiRequest<ProposalOut[]>(
    `/assist/proposals${qs ? `?${qs}` : ""}`,
    { signal },
  );
}

export function getProposal(
  proposalId: number,
  signal?: AbortSignal,
): Promise<ProposalOut> {
  return apiRequest<ProposalOut>(`/assist/proposals/${proposalId}`, {
    signal,
  });
}

export function acceptProposal(
  proposalId: number,
  signal?: AbortSignal,
): Promise<ProposalOut> {
  return apiRequest<ProposalOut>(`/assist/proposals/${proposalId}/accept`, {
    method: "POST",
    body: null,
    signal,
  });
}

export function rejectProposal(
  proposalId: number,
  body: RejectIn | null = { reason: "" },
  signal?: AbortSignal,
): Promise<ProposalOut> {
  return apiRequest<ProposalOut>(`/assist/proposals/${proposalId}/reject`, {
    method: "POST",
    body,
    signal,
  });
}

export function createAssistJob(
  body: JobCreateIn,
  signal?: AbortSignal,
): Promise<JobOut> {
  return apiRequest<JobOut>("/assist/jobs", {
    method: "POST",
    body,
    signal,
  });
}

export function getAssistJob(
  jobId: number,
  signal?: AbortSignal,
): Promise<JobOut> {
  return apiRequest<JobOut>(`/assist/jobs/${jobId}`, { signal });
}

export function explodeItem(
  body: ExplodeIn,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/assist/explode", {
    method: "POST",
    body,
    signal,
  });
}

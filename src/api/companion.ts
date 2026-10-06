import { apiRequest } from "./client";

/** D16 companion — contract 0.1.19 (typed here until schema regen). */

export type ChatRole = "user" | "assistant";

export type ChatMessage = { role: ChatRole; content: string };

export type ChatOut = { reply: string; model: string };

export type BriefTip = { title: string; body: string };

export type BriefOut = {
  service_date: string;
  generated_at: string;
  model: string;
  tips: BriefTip[];
};

export function postCompanionChat(
  messages: ChatMessage[],
  serviceDate: string,
  signal?: AbortSignal,
): Promise<ChatOut> {
  return apiRequest<ChatOut>("/assist/chat", {
    method: "POST",
    body: { messages, service_date: serviceDate },
    signal,
  });
}

export function getDailyBrief(
  serviceDate: string,
  refresh = false,
  signal?: AbortSignal,
): Promise<BriefOut> {
  const q = new URLSearchParams({ service_date: serviceDate });
  if (refresh) q.set("refresh", "true");
  return apiRequest<BriefOut>(`/assist/daily-brief?${q.toString()}`, {
    signal,
  });
}

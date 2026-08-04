import { apiRequest } from "./client";
import type {
  BoardOut,
  ComponentTickOut,
  ItemNoteOut,
  LineOut,
  NoteIn,
  OpenDayIn,
  OpenSectionIn,
  QuickAddIn,
  ServiceDayOut,
  TickIn,
} from "./types";

export function openDay(
  body: OpenDayIn,
  signal?: AbortSignal,
): Promise<ServiceDayOut> {
  return apiRequest<ServiceDayOut>("/boards/days/open", {
    method: "POST",
    body,
    signal,
  });
}

export function getDay(
  serviceDate: string,
  signal?: AbortSignal,
): Promise<ServiceDayOut> {
  return apiRequest<ServiceDayOut>(
    `/boards/days/${encodeURIComponent(serviceDate)}`,
    { signal },
  );
}

export function openSection(
  serviceDate: string,
  section: string,
  body: OpenSectionIn | null = { generate_lines: true },
  signal?: AbortSignal,
): Promise<BoardOut> {
  return apiRequest<BoardOut>(
    `/boards/days/${encodeURIComponent(serviceDate)}/sections/${encodeURIComponent(section)}/open`,
    { method: "POST", body, signal },
  );
}

export function getBoard(
  serviceDate: string,
  section: string,
  signal?: AbortSignal,
): Promise<BoardOut> {
  return apiRequest<BoardOut>(
    `/boards/days/${encodeURIComponent(serviceDate)}/sections/${encodeURIComponent(section)}`,
    { signal },
  );
}

export function tickLine(
  lineId: number,
  body: TickIn | null = null,
  signal?: AbortSignal,
): Promise<LineOut> {
  return apiRequest<LineOut>(`/boards/lines/${lineId}/tick`, {
    method: "POST",
    body,
    signal,
  });
}

export function untickLine(
  lineId: number,
  signal?: AbortSignal,
): Promise<LineOut> {
  return apiRequest<LineOut>(`/boards/lines/${lineId}/untick`, {
    method: "POST",
    body: null,
    signal,
  });
}

export function tickComponent(
  componentId: number,
  signal?: AbortSignal,
): Promise<ComponentTickOut> {
  return apiRequest<ComponentTickOut>(
    `/boards/components/${componentId}/tick`,
    { method: "POST", body: null, signal },
  );
}

export function untickComponent(
  componentId: number,
  signal?: AbortSignal,
): Promise<ComponentTickOut> {
  return apiRequest<ComponentTickOut>(
    `/boards/components/${componentId}/untick`,
    { method: "POST", body: null, signal },
  );
}

export function quickAddLine(
  body: QuickAddIn,
  signal?: AbortSignal,
): Promise<LineOut> {
  return apiRequest<LineOut>("/boards/lines/quick-add", {
    method: "POST",
    body,
    signal,
  });
}

export function setLineNotes(
  lineId: number,
  body: NoteIn,
  signal?: AbortSignal,
): Promise<LineOut> {
  return apiRequest<LineOut>(`/boards/lines/${lineId}/notes`, {
    method: "PATCH",
    body,
    signal,
  });
}

export function setItemNotes(
  itemId: number,
  body: NoteIn,
  signal?: AbortSignal,
): Promise<ItemNoteOut> {
  return apiRequest<ItemNoteOut>(`/items/${itemId}/notes`, {
    method: "PATCH",
    body,
    signal,
  });
}

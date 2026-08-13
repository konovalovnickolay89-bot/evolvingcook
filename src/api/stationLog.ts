import { apiRequest } from "./client";

export type StorageAreaOut = {
  id: number;
  name: string;
  kind: string;
};

export type StationLogLineOut = {
  id: number;
  kind: string;
  text: string;
  action: string;
  qty: number | null;
  unit: string;
  area_id: number | null;
  area_name: string;
  item_id: number | null;
  item_name: string;
  default_area: { id: number; name: string; kind: string } | null;
  line_id: number | null;
  use_by: string | null;
  status: "open" | "done";
  source: string;
  carried_from_id: number | null;
  from_yesterday: boolean;
  walk_count: {
    walk_id: number;
    counted_qty: number | null;
    skipped: boolean;
    area_id: number | null;
    area_name: string;
  } | null;
  created_at: string | null;
  done_at: string | null;
};

export type StationLogOut = {
  service_date: string;
  section: string;
  open_count: number;
  lines: StationLogLineOut[];
  by_kind: Record<string, StationLogLineOut[]>;
};

export type LogLineIn = {
  kind: string;
  text: string;
  action?: string;
  qty?: number | null;
  unit?: string;
  area_id?: number | null;
  item_id?: number | null;
  line_id?: number | null;
  use_by?: string | null;
};

export type SuggestOut = {
  provider: string;
  created_count: number;
  created: StationLogLineOut[];
  queued?: boolean;
  job_id?: number;
  fell_back?: boolean;
  error?: string;
};

function logPath(serviceDate: string, section: string): string {
  return `/boards/days/${encodeURIComponent(serviceDate)}/sections/${encodeURIComponent(section)}/log`;
}

export function listStorageAreas(
  signal?: AbortSignal,
): Promise<StorageAreaOut[]> {
  return apiRequest<StorageAreaOut[]>("/boards/storage-areas", { signal });
}

export function getStationLog(
  serviceDate: string,
  section: string,
  signal?: AbortSignal,
): Promise<StationLogOut> {
  return apiRequest<StationLogOut>(logPath(serviceDate, section), { signal });
}

export function createStationLogLine(
  serviceDate: string,
  section: string,
  body: LogLineIn,
  signal?: AbortSignal,
): Promise<StationLogLineOut> {
  return apiRequest<StationLogLineOut>(logPath(serviceDate, section), {
    method: "POST",
    body,
    signal,
  });
}

export function patchStationLogLine(
  serviceDate: string,
  section: string,
  lineId: number,
  body: Partial<LogLineIn> & { status?: "open" | "done" },
  signal?: AbortSignal,
): Promise<StationLogLineOut> {
  return apiRequest<StationLogLineOut>(
    `${logPath(serviceDate, section)}/${lineId}`,
    { method: "PATCH", body, signal },
  );
}

export function suggestStationLog(
  serviceDate: string,
  section: string,
  signal?: AbortSignal,
): Promise<SuggestOut> {
  return apiRequest<SuggestOut>(`${logPath(serviceDate, section)}/suggest`, {
    method: "POST",
    body: {},
    signal,
  });
}

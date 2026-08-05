import { apiRequest } from "./client";
import type {
  SectionSettingOut,
  SectionSettingPatchIn,
  SectionSettingsListOut,
} from "./types";

export function getSectionSettings(
  signal?: AbortSignal,
): Promise<SectionSettingsListOut> {
  return apiRequest<SectionSettingsListOut>("/sections/settings", { signal });
}

export function patchSectionSettings(
  section: string,
  body: SectionSettingPatchIn,
  signal?: AbortSignal,
): Promise<SectionSettingOut> {
  return apiRequest<SectionSettingOut>(
    `/sections/${encodeURIComponent(section)}/settings`,
    { method: "PATCH", body, signal },
  );
}

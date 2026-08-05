import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchVersion } from "@/api/client";
import { EXPECTED_CONTRACT_VERSION } from "@/contract";
import { forceAppRefresh } from "@/lib/forceRefresh";

export function VersionBanner() {
  const [busy, setBusy] = useState(false);

  const q = useQuery({
    queryKey: ["api", "version"],
    queryFn: ({ signal }) => fetchVersion(signal),
    staleTime: 30_000,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchInterval: 5 * 60_000,
  });

  if (q.isError) {
    // Offline / CORS — do not block shell; PWA must still load
    return null;
  }

  if (!q.data) return null;

  const remote = q.data.contract_version;
  if (remote === EXPECTED_CONTRACT_VERSION) return null;

  return (
    <div className="banner banner--skew" role="alert">
      <span>
        Contract moved ({EXPECTED_CONTRACT_VERSION} → {remote}). Load the new
        app build.
      </span>
      <button
        type="button"
        className="banner__action"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void forceAppRefresh();
        }}
      >
        {busy ? "Refreshing…" : "Refresh"}
      </button>
    </div>
  );
}

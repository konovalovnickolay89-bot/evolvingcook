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

  // Which side is behind? Refreshing only helps when the APP is the old one.
  const serverBehind = compareVersions(remote, EXPECTED_CONTRACT_VERSION) < 0;

  if (serverBehind) {
    return (
      <div className="banner banner--skew" role="alert">
        <span>
          Kitchen server is behind this app ({remote} &lt;{" "}
          {EXPECTED_CONTRACT_VERSION}) — newest features wait on a backend
          update. Refreshing won't clear this.
        </span>
      </div>
    );
  }

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

/** Numeric dotted-version compare: negative when a < b. */
function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => Number(n) || 0);
  const pb = b.split(".").map((n) => Number(n) || 0);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i += 1) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

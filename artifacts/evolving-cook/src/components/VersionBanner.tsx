import { useQuery } from "@tanstack/react-query";
import { fetchVersion } from "@/api/client";
import { EXPECTED_CONTRACT_VERSION } from "@/contract";

export function VersionBanner() {
  const q = useQuery({
    queryKey: ["api", "version"],
    queryFn: ({ signal }) => fetchVersion(signal),
    staleTime: 60_000,
    retry: 1,
    refetchOnWindowFocus: true,
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
        Contract moved ({EXPECTED_CONTRACT_VERSION} → {remote}). Refresh needed.
      </span>
      <button
        type="button"
        className="banner__action"
        onClick={() => window.location.reload()}
      >
        Refresh
      </button>
    </div>
  );
}

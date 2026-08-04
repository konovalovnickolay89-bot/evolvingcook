import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptProposal,
  listProposals,
  rejectProposal,
} from "@/api/assist";
import type { ProposalOut } from "@/api/types";
import { ProposalCard } from "@/components/ProposalCard";
import { EmptyState, LoadingState } from "@/components/AppShell";

type Filter = "pending" | "accepted" | "rejected" | "all";

type Props = {
  onBack: () => void;
};

export function InboxPage({ onBack }: Props) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("pending");
  const [kind, setKind] = useState<string>("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["proposals", "inbox", filter, kind],
    queryFn: ({ signal }) =>
      listProposals(
        {
          status: filter === "all" ? null : filter,
          kind: kind || null,
          limit: 50,
        },
        signal,
      ),
    retry: false,
    refetchInterval: 8000,
  });

  const kinds = useMemo(() => {
    const set = new Set<string>();
    for (const p of q.data ?? []) set.add(p.kind);
    return [...set].sort();
  }, [q.data]);

  const list = useMemo(() => {
    const rows = [...(q.data ?? [])];
    rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
    return rows;
  }, [q.data]);

  const acceptMut = useMutation({
    mutationFn: (p: ProposalOut) => acceptProposal(p.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await qc.invalidateQueries({ queryKey: ["board"] });
    },
  });

  const rejectMut = useMutation({
    mutationFn: ({ p, reason }: { p: ProposalOut; reason: string }) =>
      rejectProposal(p.id, { reason }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });

  const assistDown =
    q.isError &&
    q.error instanceof Error &&
    /A2A|unreachable|Network|Failed to fetch/i.test(q.error.message);

  return (
    <div className="stack">
      <button type="button" className="link-back" onClick={onBack}>
        ← Day home
      </button>
      <div>
        <h2 className="page-title">Proposals</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Review queue only — accept or reject. No chat.
        </p>
      </div>

      {assistDown ? (
        <p className="board-row__meta" style={{ color: "var(--comment)" }}>
          assist offline
        </p>
      ) : null}

      <div className="face-toggle" role="tablist" aria-label="Status filter">
        {(["pending", "accepted", "rejected", "all"] as Filter[]).map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={filter === f}
            className={`face-toggle__btn${filter === f ? " is-on" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f}
          </button>
        ))}
      </div>

      {kinds.length > 0 ? (
        <div className="board-line__checks" style={{ flexWrap: "wrap" }}>
          <button
            type="button"
            className={`chip${!kind ? " is-on" : ""}`}
            onClick={() => setKind("")}
          >
            all kinds
          </button>
          {kinds.map((k) => (
            <button
              key={k}
              type="button"
              className={`chip${kind === k ? " is-on" : ""}`}
              onClick={() => setKind(k)}
            >
              {k}
            </button>
          ))}
        </div>
      ) : null}

      {error ? <p className="field__error">{error}</p> : null}
      {q.isLoading ? <LoadingState label="Loading proposals…" /> : null}

      {!q.isLoading && list.length === 0 ? (
        <EmptyState
          title="No proposals waiting."
          body={
            filter === "pending"
              ? "Nothing to review."
              : "No cards in this filter."
          }
        />
      ) : null}

      <div className="stack" style={{ gap: "var(--space-03)" }}>
        {list.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            busy={busyId === p.id}
            onAccept={async (pr) => {
              setBusyId(pr.id);
              setError(null);
              try {
                await acceptMut.mutateAsync(pr);
              } catch (e) {
                setError(e instanceof Error ? e.message : "Accept failed");
              } finally {
                setBusyId(null);
              }
            }}
            onReject={async (pr, reason) => {
              setBusyId(pr.id);
              setError(null);
              try {
                await rejectMut.mutateAsync({ p: pr, reason });
              } catch (e) {
                setError(e instanceof Error ? e.message : "Reject failed");
              } finally {
                setBusyId(null);
              }
            }}
          />
        ))}
      </div>
    </div>
  );
}

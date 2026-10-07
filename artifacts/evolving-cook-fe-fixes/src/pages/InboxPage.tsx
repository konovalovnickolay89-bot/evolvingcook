import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptProposal,
  createAssistJob,
  listProposals,
  rejectProposal,
} from "@/api/assist";
import type { ProposalOut } from "@/api/types";
import { ProposalCard } from "@/components/ProposalCard";
import { EmptyState, LoadingState } from "@/components/AppShell";

/** Presentation: To review / Done — not raw status enums */
type Filter = "review" | "done";

type Props = {
  onBack: () => void;
};

function isParseErrorCard(p: ProposalOut): boolean {
  return Boolean(p.parse_error?.trim());
}

export function InboxPage({ onBack }: Props) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("review");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["proposals", "inbox", filter],
    queryFn: ({ signal }) =>
      listProposals(
        {
          // API still uses pending|accepted|rejected — map UI filter
          status: filter === "review" ? "pending" : null,
          limit: 50,
        },
        signal,
      ),
    retry: false,
    refetchInterval: 8000,
  });

  const list = useMemo(() => {
    let rows = [...(q.data ?? [])];
    if (filter === "done") {
      rows = rows.filter((p) => p.status === "accepted" || p.status === "rejected");
    } else {
      rows = rows.filter((p) => p.status === "pending");
    }
    rows.sort((a, b) => {
      const ae = isParseErrorCard(a) ? 0 : 1;
      const be = isParseErrorCard(b) ? 0 : 1;
      if (ae !== be) return ae - be;
      return b.created_at.localeCompare(a.created_at);
    });
    return rows;
  }, [q.data, filter]);

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
      await qc.invalidateQueries({ queryKey: ["board"] });
    },
  });

  /** Legitimate /assist/jobs use: parse_error Rewrite → resend */
  async function onRewrite(p: ProposalOut, newText: string) {
    const c = (p.context ?? {}) as {
      line_id?: number;
      section?: string;
    };
    setBusyId(p.id);
    setError(null);
    try {
      await createAssistJob({
        kind: "parse_note",
        context: {
          text: newText,
          ...(c.line_id != null ? { line_id: c.line_id } : {}),
          ...(c.section ? { section: c.section } : {}),
        },
      });
      // Dismiss old parse_error card
      await rejectProposal(p.id, { reason: "rewritten" });
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await qc.invalidateQueries({ queryKey: ["board"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rewrite failed");
    } finally {
      setBusyId(null);
    }
  }

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
        {(
          [
            ["review", "To review"],
            ["done", "Done"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={filter === id}
            className={`face-toggle__btn${filter === id ? " is-on" : ""}`}
            onClick={() => setFilter(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? <p className="field__error">{error}</p> : null}
      {q.isLoading ? <LoadingState label="Loading proposals…" /> : null}

      {!q.isLoading && list.length === 0 ? (
        <EmptyState
          title="No proposals waiting."
          body={
            filter === "review" ? "Nothing to review." : "No decided cards yet."
          }
        />
      ) : null}

      <div className="stack" style={{ gap: "var(--space-03)" }}>
        {list.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            compact
            inbox
            busy={busyId === p.id}
            onAccept={async (pr) => {
              if (isParseErrorCard(pr)) return;
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
            onRewrite={onRewrite}
          />
        ))}
      </div>
    </div>
  );
}

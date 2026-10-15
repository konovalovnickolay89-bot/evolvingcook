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
import { todayServiceDate } from "@/lib/dates";
import { proposalServiceDate } from "@/lib/proposalTarget";

/** Presentation: To review / Done — not raw status enums */
type Filter = "review" | "done";

type Props = {
  onBack: () => void;
};

function isParseErrorCard(p: ProposalOut): boolean {
  return Boolean(p.parse_error?.trim());
}

/** Belongs to a service day that's already gone — nothing left to act on. */
function isPastDay(p: ProposalOut): boolean {
  const d = proposalServiceDate(p);
  return d != null && d < todayServiceDate();
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
      rows = rows.filter(
        (p) => p.status === "accepted" || p.status === "rejected",
      );
    } else {
      rows = rows.filter((p) => p.status === "pending");
    }
    rows.sort((a, b) => {
      const ae = isParseErrorCard(a) ? 0 : 1;
      const be = isParseErrorCard(b) ? 0 : 1;
      if (ae !== be) return ae - be;
      // Done: most recently decided first
      const ak = (filter === "done" && a.decided_at) || a.created_at;
      const bk = (filter === "done" && b.decided_at) || b.created_at;
      return bk.localeCompare(ak);
    });
    return rows;
  }, [q.data, filter]);

  const current =
    filter === "review" ? list.filter((p) => !isPastDay(p)) : list;
  const past = filter === "review" ? list.filter(isPastDay) : [];
  const [clearing, setClearing] = useState(false);

  async function rejectPast() {
    if (
      !window.confirm(
        `Reject ${past.length} proposal(s) for past service days?`,
      )
    )
      return;
    setClearing(true);
    setError(null);
    try {
      for (const p of past) await rejectProposal(p.id, { reason: "expired" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setClearing(false);
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await qc.invalidateQueries({ queryKey: ["board"] });
    }
  }

  const acceptMut = useMutation({
    mutationFn: ({
      p,
      overlay,
    }: {
      p: ProposalOut;
      overlay?: Record<string, unknown>;
    }) => acceptProposal(p.id, overlay ? { proposal: overlay } : null),
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
      await rejectProposal(p.id, { reason: "rewritten" });
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      await qc.invalidateQueries({ queryKey: ["board"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rewrite failed");
    } finally {
      setBusyId(null);
    }
  }

  const renderCard = (p: ProposalOut) => (
    <ProposalCard
      key={p.id}
      proposal={p}
      compact
      inbox
      busy={busyId === p.id}
      onAccept={async (pr, overlay) => {
        if (isParseErrorCard(pr)) return;
        setBusyId(pr.id);
        setError(null);
        try {
          await acceptMut.mutateAsync({ p: pr, overlay });
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
  );

  const assistDown =
    q.isError &&
    q.error instanceof Error &&
    /A2A|unreachable|Network|Failed to fetch/i.test(q.error.message);

  return (
    <div className="stack">
      <button type="button" className="link-back" onClick={onBack}>
        ← Back
      </button>
      <div>
        <h2 className="page-title">Proposals</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Suggestions from assist — quantities, prep steps, ingredients and
          notes. Accept to apply to the board, or reject.
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
        {current.map(renderCard)}
      </div>

      {past.length > 0 ? (
        <>
          <p className="inbox-group">
            <span>Past service days · {past.length}</span>
            <button
              type="button"
              className="chip chip--danger"
              disabled={clearing}
              onClick={() => void rejectPast()}
            >
              {clearing ? "Rejecting…" : "Reject all"}
            </button>
          </p>
          <div className="stack" style={{ gap: "var(--space-03)" }}>
            {past.map(renderCard)}
          </div>
        </>
      ) : null}
    </div>
  );
}

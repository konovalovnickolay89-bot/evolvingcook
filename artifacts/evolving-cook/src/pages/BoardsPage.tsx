import { EmptyState } from "@/components/AppShell";

const SECTIONS = [
  { id: "skybar", label: "Skybar", mode: "check", phase: "1.5" },
  { id: "breakfast_buffet", label: "Breakfast buffet", mode: "replenish", phase: "1.5" },
  { id: "a_la_carte", label: "À la carte", mode: "—", phase: "4" },
  { id: "banquet_buffet", label: "Banquet buffet", mode: "—", phase: "4" },
  { id: "banqueting", label: "Banqueting", mode: "—", phase: "4" },
  { id: "canteen", label: "Canteen", mode: "—", phase: "4" },
] as const;

export function BoardsPage() {
  return (
    <div className="stack">
      <div>
        <h2 className="page-title">Sections</h2>
        <p className="page-lead">
          MEP / service boards land in Phase 1.5. Skybar (check) first, then
          breakfast buffet (replenish).
        </p>
      </div>

      <div className="board" role="list">
        <div className="board__section-label">Kitchen sections</div>
        {SECTIONS.map((s) => (
          <div
            key={s.id}
            className="board-row"
            role="listitem"
            style={{ cursor: "default" }}
          >
            <span
              className="board-row__badge board-row__badge--check"
              style={{ opacity: s.phase === "1.5" ? 1 : 0.4 }}
            >
              {s.phase === "1.5" ? "·" : "·"}
            </span>
            <div className="board-row__main">
              <span className="board-row__name">{s.label}</span>
              <span className="board-row__meta">
                {s.id} · phase {s.phase}
              </span>
            </div>
            <span
              className="board-row__check-state board-row__check-state--present"
              style={{ minWidth: "3.5rem" }}
            >
              {s.mode}
            </span>
          </div>
        ))}
      </div>

      <EmptyState
        title="No live board yet"
        body="API board endpoints ship with Phase 1.5. Row component is ready under Rows."
      />
    </div>
  );
}

import { BoardRow, DEMO_ROWS } from "@/components/BoardRow";

export function RowsDemoPage() {
  return (
    <div className="stack">
      <div>
        <h2 className="page-title">Board row</h2>
        <p className="page-lead">
          Terminal feel — badge left, mono tabular numerals right. Tap any row
          for breakdown. Three modes: P produce · R replenish · C check.
        </p>
        <div className="legend">
          <span className="legend__item">
            <span
              className="legend__swatch"
              style={{ background: "var(--comment)" }}
            />
            proposed
          </span>
          <span className="legend__item">
            <span
              className="legend__swatch"
              style={{ background: "var(--fg)" }}
            />
            planned
          </span>
          <span className="legend__item">
            <span
              className="legend__swatch"
              style={{ background: "var(--orange)" }}
            />
            diverged
          </span>
          <span className="legend__item">
            <span
              className="legend__swatch"
              style={{ background: "var(--cyan)" }}
            />
            actual
          </span>
        </div>
      </div>

      <div className="board">
        <div className="board__section-label">Demo lines (Phase 0 gate)</div>
        {DEMO_ROWS.map((row) => (
          <BoardRow key={`${row.mode}-${row.name}`} {...row} />
        ))}
      </div>
    </div>
  );
}

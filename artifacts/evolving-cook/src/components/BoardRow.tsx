import { useState } from "react";

export type LineMode = "produce" | "replenish" | "check";
export type CheckState = "present" | "confirm" | "86";

export type ProduceNums = {
  proposed: number | null;
  planned: number | null;
  actual: number | null;
  /** 0–1 progress toward planned; optional */
  progress?: number | null;
};

export type ReplenishNums = {
  par: number | null;
  onHand: number | null;
  topUp: number | null;
};

export type BoardRowProps = {
  mode: LineMode;
  name: string;
  meta?: string;
  produce?: ProduceNums;
  replenish?: ReplenishNums;
  check?: CheckState;
  /** Breakdown shown on tap — keys already from API line */
  breakdown?: Array<{ label: string; value: string }>;
  onActivate?: () => void;
};

function formatNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Number.isInteger(n)) return String(n);
  return String(n);
}

function plannedClass(planned: number | null, proposed: number | null): string {
  if (planned === null) return "board-row__num num--planned";
  if (proposed !== null && planned !== proposed) {
    return "board-row__num num--diverged";
  }
  return "board-row__num num--planned";
}

function ModeBadge({ mode }: { mode: LineMode }) {
  const glyph = mode === "produce" ? "P" : mode === "replenish" ? "R" : "C";
  return (
    <span
      className={`board-row__badge board-row__badge--${mode}`}
      aria-label={mode}
    >
      {glyph}
    </span>
  );
}

export function BoardRow(props: BoardRowProps) {
  const [open, setOpen] = useState(false);
  const is86 = props.mode === "check" && props.check === "86";

  const progress =
    props.mode === "produce" ? (props.produce?.progress ?? null) : null;

  return (
    <div>
      <button
        type="button"
        className={`board-row${is86 ? " board-row--86" : ""}`}
        onClick={() => {
          setOpen((v) => !v);
          props.onActivate?.();
        }}
        aria-expanded={open}
      >
        <ModeBadge mode={props.mode} />
        <div className="board-row__main">
          <span className="board-row__name">{props.name}</span>
          {props.meta ? (
            <span className="board-row__meta">{props.meta}</span>
          ) : null}
        </div>

        {props.mode === "produce" && props.produce ? (
          <div
            className="board-row__num-group"
            aria-label="proposed planned actual"
          >
            <span className="board-row__num num--proposed" title="Proposed">
              {formatNum(props.produce.proposed)}
            </span>
            <span
              className={plannedClass(
                props.produce.planned,
                props.produce.proposed,
              )}
              title="Planned"
            >
              {formatNum(props.produce.planned)}
            </span>
            <span className="board-row__num num--actual" title="Actual">
              {formatNum(props.produce.actual)}
            </span>
          </div>
        ) : null}

        {props.mode === "replenish" && props.replenish ? (
          <div
            className="board-row__num-group"
            aria-label="par on-hand top-up"
          >
            <span className="board-row__num num--proposed" title="Par">
              {formatNum(props.replenish.par)}
            </span>
            <span className="board-row__num num--planned" title="On hand">
              {formatNum(props.replenish.onHand)}
            </span>
            <span
              className={
                props.replenish.topUp != null && props.replenish.topUp > 0
                  ? "board-row__num num--diverged"
                  : "board-row__num num--actual"
              }
              title="Top-up"
            >
              {formatNum(props.replenish.topUp)}
            </span>
          </div>
        ) : null}

        {props.mode === "check" && props.check ? (
          <div className="board-row__nums">
            <span
              className={`board-row__check-state board-row__check-state--${props.check}`}
            >
              {props.check === "present"
                ? "present"
                : props.check === "confirm"
                  ? "ok"
                  : "86"}
            </span>
          </div>
        ) : null}

        {progress != null ? (
          <div className="board-row__bar" aria-hidden>
            <div
              className={`board-row__bar-fill${
                progress > 1 ? " board-row__bar-fill--over" : ""
              }`}
              style={{
                width: `${Math.min(100, Math.max(0, progress * 100))}%`,
              }}
            />
          </div>
        ) : null}
      </button>

      {open && props.breakdown && props.breakdown.length > 0 ? (
        <div className="board-row-detail" role="region" aria-label="Breakdown">
          <div className="board-row-detail__grid">
            {props.breakdown.map((row) => (
              <div key={row.label} style={{ display: "contents" }}>
                <span className="board-row-detail__k">{row.label}</span>
                <span className="board-row-detail__v">{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Demo rows for Phase 0 gate screenshot — not live API data */
export const DEMO_ROWS: BoardRowProps[] = [
  {
    mode: "produce",
    name: "Chicken supreme",
    meta: "covers: banqueting",
    produce: { proposed: 120, planned: 135, actual: 48, progress: 48 / 135 },
    breakdown: [
      { label: "Proposed", value: "120" },
      { label: "Planned (you set)", value: "135" },
      { label: "Actual done", value: "48" },
      { label: "Remaining", value: "87" },
    ],
  },
  {
    mode: "produce",
    name: "Truffle mash",
    meta: "covers: banquet_buffet",
    produce: { proposed: 40, planned: 40, actual: 40, progress: 1 },
    breakdown: [
      { label: "Proposed", value: "40" },
      { label: "Planned", value: "40" },
      { label: "Actual", value: "40" },
    ],
  },
  {
    mode: "replenish",
    name: "Croissants",
    meta: "breakfast_buffet",
    replenish: { par: 48, onHand: 12, topUp: 36 },
    breakdown: [
      { label: "Par", value: "48" },
      { label: "On hand", value: "12" },
      { label: "Top-up", value: "36" },
    ],
  },
  {
    mode: "replenish",
    name: "Orange juice",
    meta: "breakfast_buffet",
    replenish: { par: 8, onHand: 8, topUp: 0 },
    breakdown: [
      { label: "Par", value: "8" },
      { label: "On hand", value: "8" },
      { label: "Top-up", value: "0" },
    ],
  },
  {
    mode: "check",
    name: "Espresso machine",
    meta: "skybar",
    check: "confirm",
    breakdown: [{ label: "State", value: "confirmed" }],
  },
  {
    mode: "check",
    name: "Oat milk",
    meta: "skybar",
    check: "86",
    breakdown: [{ label: "State", value: "86 — not available" }],
  },
  {
    mode: "check",
    name: "Ice well",
    meta: "skybar",
    check: "present",
    breakdown: [{ label: "State", value: "present (unconfirmed)" }],
  },
];

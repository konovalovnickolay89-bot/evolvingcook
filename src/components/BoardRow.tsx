import { useState } from "react";

export type LineMode = "produce" | "replenish" | "check";
export type CheckState = "present" | "confirm" | "86";

/** D14 note→assist chip under the name */
export type NoteAssistState = "idle" | "parsing" | "ready";

export type ProduceNums = {
  proposed: number | null;
  planned: number | null;
  actual: number | null;
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
  /** D12/D14: today's line note as --comment chip */
  noteChip?: string | null;
  /** D14 template notes — same chip family + ↻ glyph */
  templateNoteChip?: string | null;
  /** ··· parsing | A proposal ready | silence */
  noteAssistState?: NoteAssistState;
  houseMade?: boolean;
  produce?: ProduceNums;
  replenish?: ReplenishNums;
  check?: CheckState;
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

function NoteAssistChip({ state }: { state: NoteAssistState }) {
  if (state === "idle") return null;
  if (state === "parsing") {
    return (
      <span className="note-assist-chip note-assist-chip--parsing" title="Parsing">
        ···
      </span>
    );
  }
  return (
    <span
      className="note-assist-chip note-assist-chip--ready"
      title="Proposal ready"
    >
      <span className="note-assist-chip__a" aria-hidden>
        A
      </span>
      proposal ready
    </span>
  );
}

export function BoardRow(props: BoardRowProps) {
  const [open, setOpen] = useState(false);
  const is86 = props.mode === "check" && props.check === "86";

  const progress =
    props.mode === "produce" ? (props.produce?.progress ?? null) : null;

  const assist = props.noteAssistState ?? "idle";

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
          <span className="board-row__name-row">
            <span className="board-row__name">{props.name}</span>
            {props.houseMade ? (
              <span className="house-tag" title="House made">
                H
              </span>
            ) : null}
          </span>
          {props.templateNoteChip ? (
            <span className="note-chip note-chip--template">
              <span className="note-chip__repeat" aria-hidden>
                ↻
              </span>
              {props.templateNoteChip}
            </span>
          ) : null}
          {props.noteChip ? (
            <span className="note-chip">{props.noteChip}</span>
          ) : null}
          <NoteAssistChip state={assist} />
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
              className={`board-row__check-state board-row__check-state--${
                props.check === "86"
                  ? "86"
                  : props.check === "confirm"
                    ? "ok"
                    : "present"
              }`}
            >
              {props.check === "confirm"
                ? "OK"
                : props.check === "86"
                  ? "86"
                  : "PRESENT"}
            </span>
          </div>
        ) : null}

        {progress != null ? (
          <div
            className="board-row__bar"
            role="progressbar"
            aria-valuenow={Math.round(progress * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span
              className="board-row__bar-fill"
              style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }}
            />
          </div>
        ) : null}
      </button>

      {open && props.breakdown && props.breakdown.length > 0 ? (
        <div className="board-row-detail">
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

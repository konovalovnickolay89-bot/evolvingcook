import { useState } from "react";
import { SECTION_LABELS, type SectionId, type SectionMode } from "@/contract";

type Props = {
  section: string;
  recommendation: string | null | undefined;
  guidedDefault?: boolean;
  busy?: boolean;
  onChoose: (mode: SectionMode, guided?: boolean) => void;
};

/**
 * F1 — chef mode question. Exact copy from FE-SECTION-MODES.md.
 * Never auto-applies mode_recommendation.
 */
export function ModePrompt({
  section,
  recommendation,
  guidedDefault,
  busy,
  onChoose,
}: Props) {
  const [picking, setPicking] = useState<SectionMode | null>(null);
  const label =
    SECTION_LABELS[section as SectionId] ?? section.replace(/_/g, " ");
  const rec =
    recommendation === "counts" || recommendation === "ordering"
      ? recommendation
      : null;
  const banquet =
    section === "banqueting" || section === "banquet_buffet";
  const guided = guidedDefault ?? banquet;

  function pick(mode: SectionMode) {
    setPicking(mode);
    onChoose(mode, banquet ? guided : undefined);
  }

  return (
    <div className="mode-prompt" role="group" aria-label="Section mode">
      <p className="mode-prompt__q">
        On this board, do the numbers matter — or is it really about what to
        order?
      </p>
      <div className="mode-prompt__actions">
        <button
          type="button"
          className={`mode-prompt__btn mode-prompt__btn--counts${
            rec === "counts" ? " is-hint" : ""
          }`}
          disabled={busy}
          onClick={() => pick("counts")}
        >
          <span className="mode-prompt__btn-title">
            {picking === "counts" && busy ? "Saving…" : "Counts matter"}
          </span>
          <span className="mode-prompt__btn-sub">
            Quantities tracked, three-number rows, Assist drafts prep/order
            maths
          </span>
        </button>
        <button
          type="button"
          className={`mode-prompt__btn mode-prompt__btn--ordering${
            rec === "ordering" ? " is-hint" : ""
          }`}
          disabled={busy}
          onClick={() => pick("ordering")}
        >
          <span className="mode-prompt__btn-title">
            {picking === "ordering" && busy ? "Saving…" : "Just ordering"}
          </span>
          <span className="mode-prompt__btn-sub">
            Clean menu reference (dish → ingredients), Assist only flags what
            to order
          </span>
        </button>
      </div>
      {rec ? (
        <p className="mode-prompt__hint">
          Assist's guess for {label}: {rec} — your call.
        </p>
      ) : null}
      <p className="mode-prompt__foot">Change any time in section settings.</p>
    </div>
  );
}

export function ModePill({
  mode,
  guided,
}: {
  mode: SectionMode | null | undefined;
  guided?: boolean;
}) {
  if (!mode) return null;
  return (
    <span
      className={`mode-pill mode-pill--${mode}`}
      title={guided ? "Guided prep on" : undefined}
    >
      {mode === "counts" ? "Counts" : "Ordering"}
      {guided ? " · guided" : ""}
    </span>
  );
}

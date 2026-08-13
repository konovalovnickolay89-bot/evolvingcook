import { useEffect, useState } from "react";
import type { LineComponentOut, ProductionLineOut } from "@/api/types";
import { BoardRow } from "./BoardRow";
import {
  checkStateFromLine,
  lineBreakdown,
  lineMeta,
  normalizeMode,
  produceNums,
  replenishNums,
} from "@/lib/lineDisplay";
import { formatDecimal } from "@/lib/decimal";
import { stockDotClass } from "@/lib/boardDepth";
import type { SectionMode } from "@/contract";
import type { BoardFace } from "@/pages/BoardPage";

type Props = {
  line: ProductionLineOut;
  face?: BoardFace;
  section?: string;
  /** D15 section mode — ordering hides three-number UI */
  sectionMode?: SectionMode | null;
  busy?: boolean;
  onTickLine: (line: ProductionLineOut) => void;
  onUntickLine: (line: ProductionLineOut) => void;
  onSetEightySix: (line: ProductionLineOut) => void;
  onTickComponent: (componentId: number, done: boolean) => void;
  onSaveNotes?: (line: ProductionLineOut, notes: string) => Promise<void> | void;
};

function stockAreas(c: LineComponentOut): Array<{
  area_id?: number;
  area_name: string;
  qty: number | null;
}> {
  const raw = c.stock_by_area;
  if (!Array.isArray(raw) || !raw.length) return [];
  return raw
    .map((row) => {
      if (!row || typeof row !== "object") return null;
      const r = row as Record<string, unknown>;
      const name =
        typeof r.area_name === "string"
          ? r.area_name
          : typeof r.name === "string"
            ? r.name
            : "";
      if (!name) return null;
      const qty =
        typeof r.qty === "number"
          ? r.qty
          : r.qty != null
            ? Number(r.qty)
            : null;
      return {
        area_id: typeof r.area_id === "number" ? r.area_id : undefined,
        area_name: name,
        qty: Number.isFinite(qty as number) ? (qty as number) : null,
      };
    })
    .filter((x): x is NonNullable<typeof x> => x != null);
}

export function BoardLine({
  line,
  face = "mep",
  section: _section,
  sectionMode = null,
  busy,
  onTickLine,
  onUntickLine,
  onSetEightySix,
  onTickComponent,
  onSaveNotes,
}: Props) {
  const [open, setOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState(line.notes || "");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [areaOpen, setAreaOpen] = useState<number | null>(null);

  const ordering = sectionMode === "ordering";
  const mode = normalizeMode(line.mode);
  const meta = lineMeta(line);
  const breakdown = lineBreakdown(line);
  const houseMade = Boolean(line.item_house_made);
  const doneCount = line.components.filter((c) => c.done).length;
  const totalComp = line.components.length;
  const showAs = mode;

  const orderLabel =
    (line as { order_summary_label?: string | null }).order_summary_label ||
    (line.to_order_count != null
      ? `${totalComp} items · ${line.to_order_count} to order`
      : totalComp
        ? `${totalComp} items`
        : "");

  useEffect(() => {
    setNoteDraft(line.notes || "");
  }, [line.notes, line.id]);

  async function saveNoteOnly() {
    if (!onSaveNotes) return;
    setSaveMsg(null);
    await onSaveNotes(line, noteDraft);
  }

  const templateNotes = (line.template_notes || "").trim();
  const lineNotes = (line.notes || "").trim();

  const rowMeta = ordering
    ? [orderLabel, meta].filter(Boolean).join(" · ") || undefined
    : totalComp
      ? `${meta ? `${meta} · ` : ""}${doneCount}/${totalComp} components`
      : meta || undefined;

  return (
    <div
      className={`board-line${busy ? " is-busy" : ""}${open ? " is-open" : ""}${
        face === "service" ? " board-line--service" : ""
      }${ordering ? " board-line--ordering" : ""}`}
    >
      <BoardRow
        mode={showAs}
        name={line.name}
        houseMade={houseMade}
        noteChip={lineNotes || null}
        templateNoteChip={templateNotes || null}
        meta={rowMeta}
        /* F2: ordering never shows count UI */
        produce={
          !ordering && showAs === "produce" ? produceNums(line) : undefined
        }
        replenish={
          !ordering && showAs === "replenish" ? replenishNums(line) : undefined
        }
        check={
          !ordering && showAs === "check" ? checkStateFromLine(line) : undefined
        }
        breakdown={undefined}
        onActivate={() => {
          setNoteDraft(line.notes || "");
          setOpen((v) => !v);
        }}
      />

      {open ? (
        <div className="board-line__actions">
          {line.supports_lounge ? (
            <span className="covers-chip">covers: lounge</span>
          ) : null}

          {!ordering && showAs === "check" ? (
            <div className="board-line__checks">
              <button
                type="button"
                className={`chip${checkStateFromLine(line) === "present" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onUntickLine(line)}
              >
                Present
              </button>
              <button
                type="button"
                className={`chip chip--ok${checkStateFromLine(line) === "confirm" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onTickLine(line)}
              >
                Confirm
              </button>
              <button
                type="button"
                className={`chip chip--danger${checkStateFromLine(line) === "86" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onSetEightySix(line)}
              >
                86
              </button>
            </div>
          ) : null}

          {!ordering && showAs !== "check" ? (
            <div className="board-line__checks">
              <button
                type="button"
                className={`chip${line.ticked ? " is-on chip--ok" : ""}`}
                disabled={busy}
                onClick={() =>
                  line.ticked ? onUntickLine(line) : onTickLine(line)
                }
              >
                {line.ticked ? "Done ✓" : "Mark done"}
              </button>
            </div>
          ) : null}

          {ordering ? (
            <div className="board-line__checks">
              <button
                type="button"
                className={`chip chip--danger${checkStateFromLine(line) === "86" ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => onSetEightySix(line)}
              >
                86
              </button>
            </div>
          ) : null}

          {totalComp > 0 ? (
            <div>
              <div className="board__section-label">
                {houseMade
                  ? "House-made constituents"
                  : ordering
                    ? "Ingredients"
                    : "Components"}
              </div>
              <ul className="component-list">
                {line.components
                  .slice()
                  .sort((a, b) => a.sort_order - b.sort_order)
                  .map((c) => {
                    const areas = ordering ? stockAreas(c) : [];
                    const showAreas = areaOpen === c.id;
                    return (
                      <li key={c.id}>
                        {ordering ? (
                          <div className="component-row component-row--stock">
                            <span
                              className={stockDotClass(c.stock_status)}
                              title={c.stock_status_text || c.stock_status || ""}
                              aria-label={
                                c.stock_status_text ||
                                c.stock_status ||
                                "unknown"
                              }
                            />
                            <button
                              type="button"
                              className="component-row__stock-main"
                              onClick={() =>
                                setAreaOpen((id) =>
                                  id === c.id ? null : c.id,
                                )
                              }
                            >
                              <span className="component-row__name">
                                {c.name}
                                {c.supplier_code ? (
                                  <span className="component-row__code">
                                    {" "}
                                    · {c.supplier_code}
                                  </span>
                                ) : null}
                              </span>
                              <span className="component-row__stock-meta">
                                {c.stock_status_text ||
                                  c.stock_status ||
                                  "unknown"}
                                {c.par_qty != null
                                  ? ` · par ${formatDecimal(c.par_qty)}`
                                  : ""}
                                {c.stock_qty != null
                                  ? ` · ${formatDecimal(c.stock_qty)} house`
                                  : ""}
                              </span>
                            </button>
                            {showAreas && areas.length > 0 ? (
                              <ul className="stock-areas">
                                {areas.map((a) => (
                                  <li key={`${a.area_id ?? a.area_name}`}>
                                    <span>{a.area_name}</span>
                                    <span className="num">
                                      {formatDecimal(a.qty)}
                                    </span>
                                  </li>
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        ) : (
                          <button
                            type="button"
                            className={`component-row${c.done ? " is-done" : ""}`}
                            disabled={busy}
                            onClick={() => onTickComponent(c.id, c.done)}
                          >
                            <span className="component-row__box" aria-hidden>
                              {c.done ? "✓" : ""}
                            </span>
                            <span className="component-row__name">
                              {c.name}
                              {c.supplier_item_id != null ? (
                                <span className="component-row__code">
                                  {" "}
                                  · #{c.supplier_item_id}
                                </span>
                              ) : null}
                            </span>
                            <span className="component-row__qty num">
                              {formatDecimal(c.planned_qty)}
                              {c.unit ? ` ${c.unit}` : ""}
                            </span>
                          </button>
                        )}
                      </li>
                    );
                  })}
              </ul>
            </div>
          ) : null}

          {onSaveNotes ? (
            <div className="note-edit">
              <label className="field__label" htmlFor={`note-${line.id}`}>
                Note
              </label>
              <input
                id={`note-${line.id}`}
                className="field__input"
                type="text"
                enterKeyHint="done"
                autoComplete="off"
                maxLength={500}
                value={noteDraft}
                disabled={busy}
                onChange={(e) => setNoteDraft(e.target.value)}
                placeholder="Type or dictate a note"
              />
              <div className="quick-add__row">
                <button
                  type="button"
                  className="btn btn--primary btn--block"
                  disabled={busy || noteDraft === (line.notes || "")}
                  onClick={() => {
                    void saveNoteOnly().catch((e) =>
                      setSaveMsg(
                        e instanceof Error ? e.message : "Save failed",
                      ),
                    );
                  }}
                >
                  Save
                </button>
              </div>
              {saveMsg ? <p className="field__error">{saveMsg}</p> : null}
            </div>
          ) : null}

          {!ordering ? (
            <div className="board-row-detail" style={{ padding: 0, border: 0 }}>
              <div className="board-row-detail__grid">
                {breakdown.map((row) => (
                  <div key={row.label} style={{ display: "contents" }}>
                    <span className="board-row-detail__k">{row.label}</span>
                    <span className="board-row-detail__v">{row.value}</span>
                  </div>
                ))}
                {houseMade ? (
                  <>
                    <span className="board-row-detail__k">House made</span>
                    <span className="board-row-detail__v">yes</span>
                  </>
                ) : null}
                {templateNotes ? (
                  <>
                    <span className="board-row-detail__k">Template note</span>
                    <span className="board-row-detail__v">
                      ↻ {templateNotes}
                    </span>
                  </>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRecipe,
  draftRecipe,
  getRecipe,
  patchRecipe,
  type RecipeIn,
  type RecipeIngredient,
} from "@/api/recipes";
import { ApiError } from "@/api/client";
import {
  ALL_SECTIONS,
  SECTION_LABELS,
  UK14_ALLERGENS,
  type SectionId,
} from "@/contract";
import { formatDecimal } from "@/lib/decimal";
import { EmptyState, LoadingState } from "@/components/AppShell";
import { useDictation } from "@/lib/useDictation";

type Props = {
  /** null = new recipe */
  recipeId: number | null;
  onBack: () => void;
  onSaved: (id: number) => void;
};

const EMPTY: RecipeIn = {
  name: "",
  section: "",
  base_covers: null,
  yield_qty: null,
  yield_unit: "",
  ingredients: [],
  method: [],
  allergens: [],
  notes: "",
  source: "chef",
};

function scaled(qty: number | null, factor: number | null): string {
  if (qty == null) return "—";
  if (factor == null) return formatDecimal(qty);
  const v = qty * factor;
  return formatDecimal(Math.round(v * 100) / 100);
}

export function RecipePage({ recipeId, onBack, onSaved }: Props) {
  const qc = useQueryClient();
  const isNew = recipeId == null;
  const [editing, setEditing] = useState(isNew);
  const [form, setForm] = useState<RecipeIn>(EMPTY);
  const [coversInput, setCoversInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* Companion draft (new recipes) */
  const [draftPrompt, setDraftPrompt] = useState("");
  const [drafting, setDrafting] = useState(false);
  const dictation = useDictation((t) =>
    setDraftPrompt((d) => (d ? `${d} ${t}` : t)),
  );

  const q = useQuery({
    queryKey: ["recipe", recipeId],
    queryFn: ({ signal }) => getRecipe(recipeId as number, signal),
    enabled: !isNew,
    retry: false,
  });

  useEffect(() => {
    if (q.data) {
      const { id: _id, created_at: _c, updated_at: _u, ...rest } = q.data;
      setForm(rest);
      if (q.data.base_covers) setCoversInput(String(q.data.base_covers));
    }
  }, [q.data]);

  const base = form.base_covers;
  const coversNum = Number(coversInput);
  const factor =
    base && Number.isFinite(coversNum) && coversNum > 0
      ? coversNum / base
      : null;

  function set<K extends keyof RecipeIn>(key: K, value: RecipeIn[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function setIngredient(i: number, patch: Partial<RecipeIngredient>) {
    setForm((f) => ({
      ...f,
      ingredients: f.ingredients.map((ing, idx) =>
        idx === i ? { ...ing, ...patch } : ing,
      ),
    }));
  }

  async function runDraft() {
    const prompt = draftPrompt.trim();
    if (!prompt || drafting) return;
    setDrafting(true);
    setError(null);
    try {
      const covers =
        Number.isFinite(coversNum) && coversNum > 0
          ? Math.floor(coversNum)
          : null;
      const d = await draftRecipe(prompt, covers);
      setForm((f) => ({
        ...f,
        name: d.name,
        base_covers: d.base_covers,
        yield_qty: d.yield_qty,
        yield_unit: d.yield_unit,
        ingredients: d.ingredients,
        method: d.method,
        allergens: d.allergens,
        notes: d.notes,
        source: "companion",
      }));
      if (d.base_covers) setCoversInput(String(d.base_covers));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
        setError(
          "Recipe drafting isn't on the kitchen server yet — fill the card by hand for now.",
        );
      } else if (e instanceof ApiError && e.status === 503) {
        setError("Companion offline — fill the card by hand for now.");
      } else {
        setError(e instanceof Error ? e.message : "Draft failed");
      }
    } finally {
      setDrafting(false);
    }
  }

  async function save() {
    if (!form.name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const saved = isNew
        ? await createRecipe(form)
        : await patchRecipe(recipeId, form);
      await qc.invalidateQueries({ queryKey: ["recipes"] });
      qc.setQueryData(["recipe", saved.id], saved);
      setEditing(false);
      if (isNew) onSaved(saved.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  if (!isNew && q.isLoading) {
    return <LoadingState label="Loading recipe…" />;
  }
  if (!isNew && q.isError) {
    return (
      <div className="stack">
        <button type="button" className="link-back" onClick={onBack}>
          ← Recipes
        </button>
        <EmptyState
          title="Recipe unavailable"
          body={q.error instanceof Error ? q.error.message : "Request failed"}
        />
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="day-home__title-row">
        <button type="button" className="link-back" onClick={onBack}>
          ← Recipes
        </button>
        {!editing ? (
          <button
            type="button"
            className="link-back"
            onClick={() => setEditing(true)}
          >
            Edit
          </button>
        ) : null}
      </div>

      {!editing ? (
        <>
          <div>
            <h2 className="page-title">{form.name}</h2>
            <p className="page-lead" style={{ marginBottom: 0 }}>
              {[
                form.section
                  ? (SECTION_LABELS[form.section as SectionId] ?? form.section)
                  : null,
                form.base_covers ? `base ${form.base_covers} covers` : null,
                form.yield_qty != null
                  ? `yield ${formatDecimal(form.yield_qty)} ${form.yield_unit}`.trim()
                  : null,
              ]
                .filter(Boolean)
                .join(" · ") || "Recipe card"}
            </p>
          </div>

          {form.allergens.length > 0 ? (
            <div className="kind-chips" aria-label="Allergens">
              {form.allergens.map((a) => (
                <span key={a} className="kind-chip is-on">
                  ⚠ {a}
                </span>
              ))}
            </div>
          ) : null}

          {base ? (
            <div className="tune-card">
              <label className="field" style={{ marginBottom: 0 }}>
                <span className="field__label">
                  Scale to covers (base {base})
                </span>
                <input
                  className="field__input"
                  inputMode="numeric"
                  value={coversInput}
                  onChange={(e) => setCoversInput(e.target.value)}
                />
              </label>
              {factor != null && factor !== 1 ? (
                <p className="board-row__meta">
                  ×{formatDecimal(Math.round(factor * 100) / 100)} — quantities
                  below are scaled.
                </p>
              ) : null}
            </div>
          ) : null}

          <div>
            <div className="board__section-label">Ingredients</div>
            <ul className="component-list" style={{ marginTop: 8 }}>
              {form.ingredients.map((ing, i) => (
                <li key={`${ing.name}-${i}`} className="component-row" style={{ cursor: "default" }}>
                  <span className="component-row__box" aria-hidden />
                  <span className="component-row__name">
                    {ing.name}
                    {ing.note ? (
                      <span className="component-row__code"> · {ing.note}</span>
                    ) : null}
                  </span>
                  <span className="component-row__qty num">
                    {scaled(ing.qty, factor)}
                    {ing.unit ? ` ${ing.unit}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <div className="board__section-label">Method</div>
            <ol className="recipe-method">
              {form.method.map((step, i) => (
                <li key={i} className="recipe-method__step">
                  {step}
                </li>
              ))}
            </ol>
          </div>

          {form.notes ? (
            <p className="proposal-card__quote">{form.notes}</p>
          ) : null}
        </>
      ) : (
        <>
          <h2 className="page-title">{isNew ? "New recipe" : "Edit recipe"}</h2>

          {isNew ? (
            <div className="brief-card">
              <h3 className="brief-card__title">Draft with the companion</h3>
              <p className="board-row__meta">
                Say the dish and anything that matters — it fills the card,
                you stay the chef.
              </p>
              <div className="note-capture__row">
                <input
                  className="field__input"
                  value={draftPrompt}
                  disabled={drafting}
                  onChange={(e) => setDraftPrompt(e.target.value)}
                  placeholder={
                    dictation.listening
                      ? "Listening…"
                      : "e.g. chicken supreme, jus, fondant — banqueting, 120 covers"
                  }
                />
                {dictation.supported ? (
                  <button
                    type="button"
                    className={`btn btn--ghost voice-btn${dictation.listening ? " is-listening" : ""}`}
                    aria-pressed={dictation.listening}
                    aria-label={
                      dictation.listening ? "Stop dictating" : "Dictate"
                    }
                    onClick={() =>
                      dictation.listening ? dictation.stop() : dictation.start()
                    }
                  >
                    {dictation.listening ? "◼" : "⏺"}
                  </button>
                ) : null}
              </div>
              <button
                type="button"
                className="btn btn--ghost btn--block"
                disabled={drafting || !draftPrompt.trim()}
                onClick={() => void runDraft()}
              >
                {drafting ? "Drafting…" : "Draft recipe"}
              </button>
            </div>
          ) : null}

          <label className="field">
            <span className="field__label">Name</span>
            <input
              className="field__input"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Chicken supreme, thyme jus"
            />
          </label>

          <div className="station-log__add-row">
            <label className="field">
              <span className="field__label">Section</span>
              <select
                className="field__input"
                value={form.section}
                onChange={(e) => set("section", e.target.value)}
              >
                <option value="">—</option>
                {ALL_SECTIONS.map((id) => (
                  <option key={id} value={id}>
                    {SECTION_LABELS[id as SectionId]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Base covers</span>
              <input
                className="field__input"
                inputMode="numeric"
                value={form.base_covers ?? ""}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  set(
                    "base_covers",
                    e.target.value.trim() === "" || !Number.isFinite(n) || n <= 0
                      ? null
                      : Math.floor(n),
                  );
                }}
                placeholder="—"
              />
            </label>
          </div>

          <div>
            <div className="board__section-label">Ingredients</div>
            {form.ingredients.map((ing, i) => (
              <div key={i} className="recipe-ing-edit">
                <input
                  className="field__input"
                  value={ing.name}
                  onChange={(e) => setIngredient(i, { name: e.target.value })}
                  placeholder="Ingredient"
                />
                <input
                  className="field__input"
                  inputMode="decimal"
                  value={ing.qty ?? ""}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setIngredient(i, {
                      qty:
                        e.target.value.trim() === "" || !Number.isFinite(n)
                          ? null
                          : n,
                    });
                  }}
                  placeholder="qty"
                  aria-label="Quantity"
                />
                <input
                  className="field__input"
                  value={ing.unit}
                  onChange={(e) => setIngredient(i, { unit: e.target.value })}
                  placeholder="unit"
                  aria-label="Unit"
                />
                <button
                  type="button"
                  className="btn btn--ghost"
                  aria-label="Remove ingredient"
                  onClick={() =>
                    set(
                      "ingredients",
                      form.ingredients.filter((_, idx) => idx !== i),
                    )
                  }
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn--ghost btn--block"
              onClick={() =>
                set("ingredients", [
                  ...form.ingredients,
                  { name: "", qty: null, unit: "", note: "" },
                ])
              }
            >
              + Ingredient
            </button>
          </div>

          <div>
            <div className="board__section-label">Method</div>
            {form.method.map((step, i) => (
              <div key={i} className="recipe-step-edit">
                <span className="num recipe-step-edit__n">{i + 1}</span>
                <textarea
                  className="field__input note-edit__area"
                  rows={2}
                  value={step}
                  onChange={(e) =>
                    set(
                      "method",
                      form.method.map((s, idx) =>
                        idx === i ? e.target.value : s,
                      ),
                    )
                  }
                />
                <button
                  type="button"
                  className="btn btn--ghost"
                  aria-label="Remove step"
                  onClick={() =>
                    set(
                      "method",
                      form.method.filter((_, idx) => idx !== i),
                    )
                  }
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn--ghost btn--block"
              onClick={() => set("method", [...form.method, ""])}
            >
              + Step
            </button>
          </div>

          <div>
            <div className="board__section-label">Allergens</div>
            <div className="kind-chips" style={{ marginTop: 8 }}>
              {UK14_ALLERGENS.map((a) => {
                const on = form.allergens.includes(a);
                return (
                  <button
                    key={a}
                    type="button"
                    className={`kind-chip${on ? " is-on" : ""}`}
                    aria-pressed={on}
                    onClick={() =>
                      set(
                        "allergens",
                        on
                          ? form.allergens.filter((x) => x !== a)
                          : [...form.allergens, a],
                      )
                    }
                  >
                    {a}
                  </button>
                );
              })}
            </div>
          </div>

          <label className="field">
            <span className="field__label">Notes</span>
            <textarea
              className="field__input note-edit__area"
              rows={3}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Holding, plating, watch-outs…"
            />
          </label>

          <button
            type="button"
            className="btn btn--primary btn--block"
            disabled={busy || !form.name.trim()}
            onClick={() => void save()}
          >
            {busy ? "Saving…" : "Save recipe"}
          </button>
          {!isNew ? (
            <button
              type="button"
              className="link-back"
              onClick={() => {
                setEditing(false);
                if (q.data) {
                  const { id: _i, created_at: _c, updated_at: _u, ...rest } =
                    q.data;
                  setForm(rest);
                }
              }}
            >
              Cancel
            </button>
          ) : null}
        </>
      )}

      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

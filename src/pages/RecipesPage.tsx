import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listRecipes } from "@/api/recipes";
import { ApiError } from "@/api/client";
import { SECTION_LABELS, type SectionId } from "@/contract";
import { EmptyState, LoadingState } from "@/components/AppShell";

type Props = {
  onBack: () => void;
  onOpenRecipe: (id: number) => void;
  onNewRecipe: () => void;
};

export function RecipesPage({ onBack, onOpenRecipe, onNewRecipe }: Props) {
  const [search, setSearch] = useState("");

  const q = useQuery({
    queryKey: ["recipes"],
    queryFn: ({ signal }) => listRecipes("", signal),
    retry: false,
  });

  const rows = useMemo(() => {
    const list = q.data ?? [];
    const s = search.trim().toLowerCase();
    if (!s) return list;
    return list.filter(
      (r) =>
        r.name.toLowerCase().includes(s) ||
        r.ingredients.some((i) => i.name.toLowerCase().includes(s)),
    );
  }, [q.data, search]);

  const notOnServer =
    q.isError &&
    q.error instanceof ApiError &&
    (q.error.status === 404 || q.error.status === 405);

  return (
    <div className="stack">
      <button type="button" className="link-back" onClick={onBack}>
        ← Back
      </button>
      <div>
        <h2 className="page-title">Recipes</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Your cards: spec + method. Scale by covers on the card.
        </p>
      </div>

      <button
        type="button"
        className="btn btn--primary btn--block"
        onClick={onNewRecipe}
      >
        + New recipe
      </button>

      <input
        className="field__input"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name or ingredient"
        autoComplete="off"
      />

      {q.isLoading ? <LoadingState label="Loading recipes…" /> : null}

      {notOnServer ? (
        <EmptyState
          title="Recipes aren't on the kitchen server yet"
          body="They arrive with the next backend update."
        />
      ) : q.isError ? (
        <EmptyState
          title="Could not load recipes"
          body={q.error instanceof Error ? q.error.message : "Request failed"}
        />
      ) : null}

      {q.data && rows.length === 0 ? (
        <EmptyState
          title={search ? "No match." : "No recipes yet."}
          body={
            search
              ? "Nothing with that name or ingredient."
              : "Start one — the companion can draft it from a sentence."
          }
        />
      ) : null}

      <div className="section-cards" role="list">
        {rows.map((r) => (
          <button
            key={r.id}
            type="button"
            className="section-card"
            role="listitem"
            onClick={() => onOpenRecipe(r.id)}
          >
            <div className="section-card__top">
              <span className="section-card__name">{r.name}</span>
              {r.source === "companion" ? (
                <span className="order-assist__badge" aria-label="Drafted by companion">
                  A
                </span>
              ) : null}
            </div>
            <span className="section-card__purpose">
              {[
                r.section
                  ? (SECTION_LABELS[r.section as SectionId] ?? r.section)
                  : null,
                r.base_covers ? `${r.base_covers} covers` : null,
                `${r.ingredients.length} ingredients`,
                r.allergens.length
                  ? `allergens: ${r.allergens.join(", ")}`
                  : "no listed allergens",
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

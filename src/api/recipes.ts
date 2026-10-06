import { apiRequest } from "./client";

/** D17 recipes — contract 0.1.20 (typed here until schema regen). */

export type RecipeIngredient = {
  name: string;
  qty: number | null;
  unit: string;
  note: string;
};

export type RecipeOut = {
  id: number;
  name: string;
  section: string;
  base_covers: number | null;
  yield_qty: number | null;
  yield_unit: string;
  ingredients: RecipeIngredient[];
  method: string[];
  allergens: string[];
  notes: string;
  source: string;
  created_at: string | null;
  updated_at: string | null;
};

export type RecipeIn = Omit<RecipeOut, "id" | "created_at" | "updated_at">;

export type RecipeDraftOut = Omit<RecipeIn, "section"> & { model: string };

export function listRecipes(
  q = "",
  signal?: AbortSignal,
): Promise<RecipeOut[]> {
  const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  return apiRequest<RecipeOut[]>(`/recipes${qs}`, { signal });
}

export function getRecipe(
  id: number,
  signal?: AbortSignal,
): Promise<RecipeOut> {
  return apiRequest<RecipeOut>(`/recipes/${id}`, { signal });
}

export function createRecipe(
  body: RecipeIn,
  signal?: AbortSignal,
): Promise<RecipeOut> {
  return apiRequest<RecipeOut>("/recipes", { method: "POST", body, signal });
}

export function patchRecipe(
  id: number,
  body: Partial<RecipeIn>,
  signal?: AbortSignal,
): Promise<RecipeOut> {
  return apiRequest<RecipeOut>(`/recipes/${id}`, {
    method: "PATCH",
    body,
    signal,
  });
}

export function draftRecipe(
  prompt: string,
  covers: number | null,
  signal?: AbortSignal,
): Promise<RecipeDraftOut> {
  return apiRequest<RecipeDraftOut>("/recipes/draft", {
    method: "POST",
    body: { prompt, covers },
    signal,
  });
}

# Breakfast ParLevel seed — PROPOSAL (not applied)
Status: **awaiting Mykola approval** — no ParLevel rows written.

## Template inventory (current)

| section | active templates | notes |
|---|---:|---|
| a_la_carte | 22 | Phase 1.5 done |
| breakfast_buffet | **0** | needs replenish templates + ParLevels |
| skybar | **0** | waits `sheets/skybar-mep-list.csv` |
| banquet_buffet / banqueting / canteen | 0 | later |

## Constraint from brief

Breakfast board = **replenish** lines against `ParLevel` on a **section-kind** `StorageArea`.

Section-kind areas today: **[{'id': 8, 'name': 'a la carte fridge', 'kind': 'section'}]** — only `a la carte fridge`.

**Decision needed before seed:** how breakfast maps to area kind.

| Option | Action |
|---|---|
| A (recommended) | Add StorageArea `breakfast buffet` kind=`section` (9th area; walk_order null). ParLevels hang there for board generation. Physical stock still in dairy/breakfast freezer etc. via item.default_area / walk later. |
| B | Reclassify `dairy+breakfast fridge` → kind=`section` (changes locked kind semantics of an existing seed name). |
| C | Relax generator to pull ParLevels from multiple walkin/freezer areas tagged breakfast — **needs brief change**. |

## Catalogue hits proposed as first par set

Qty are **starting guesses** (Hilton Wembley breakfast scale) — edit freely before GO.
weekday=null → applies all days (B11 nulls_distinct).

| item_id | item | base_unit | area | qty | weekday | note |
|---:|---|---|---|---:|---|---|
| 95 | Streaky bacon | ea | breakfast freezer | 40 | all | Hot breakfast protein — freezer pack |
| 92 | Plum tomatoes | ea | dairy+breakfast fridge | 30 | all | Grilled tomato / breakfast garnish |
| 66 | Unsalted butter | ea | dairy+breakfast fridge | 20 | all | Service butter pats / cooking |
| 3 | Garlic and herb butter | ea | dairy+breakfast fridge | 10 | all | Optional cooked breakfast garnish |
| 16 | Greek yoghurt | ea | dairy+breakfast fridge | 24 | all | Buffet dairy |
| 5 | Honey | ea | dry store | 6 | all | Buffet condiment |
| 7 | Cranberry sauce | ea | dairy+breakfast fridge | 4 | all | Cold buffet condiment if used |

## Classic breakfast lines **not** in catalogue yet

Create Item (name+unit) first, then ParLevel — do not invent supplier codes.

| proposed item name | unit | suggested area | suggested qty | note |
|---|---|---|---:|---|
| Eggs, shell | ea | dairy+breakfast fridge | 30 | Breakfast protein |
| Sausage, pork link | ea | breakfast freezer | 40 | Hot buffet |
| Bacon, back | ea | breakfast freezer | 30 | If distinct from streaky |
| Black pudding | ea | breakfast freezer | 15 | Hot buffet |
| Baked beans | ea | dry store | 12 | Tins/trays as ea pack |
| Hash brown | ea | breakfast freezer | 40 | Frozen |
| Mushroom, cup | g | veg fridge | 3000 | Sauté |
| Smoked salmon | g | dairy+breakfast fridge | 2000 | Cold buffet |
| Croissant | ea | fruit+pastry fridge | 40 | Pastry |
| Danish pastry | ea | fruit+pastry fridge | 30 | Pastry |
| Bread, white sliced | ea | dry store | 10 | Loaves as ea |
| Bread, brown sliced | ea | dry store | 8 | Loaves as ea |
| Orange juice | ml | dairy+breakfast fridge | 10000 | Dispenser |
| Milk, semi-skimmed | ml | dairy+breakfast fridge | 20000 | Cereal/coffee |
| Cornflakes | g | dry store | 3000 | Cereal |
| Muesli | g | dry store | 3000 | Cereal |
| Porridge oats | g | dry store | 5000 | Hot cereal |

## After approval

1. Resolve area option A/B/C.
2. Create missing Items (name+unit only).
3. `ParLevel` rows (item, area, weekday=null, qty).
4. DishTemplate or generator path: breakfast_buffet replenish lines from those pars.
5. Do **not** apply until explicit GO on this list.

# Ordering guide capture — 2026-08-04

Source: 10 phone photos of printed house ordering sheets (menu MEP + breakfast + sky bar + proteins + dry store).

## Files
| File | Content |
|------|---------|
| `ordering-guide-all.csv` | Full consolidated rows |
| `menu-mep-*.csv` | À la carte / grill / pizza / salads / birch street dishes |
| `breakfast.csv` | Breakfast ordering + bakery + egg/deli/salad bar |
| `sky-bar.csv` | Sky bar SKUs (supplier × code × description) |
| `proteins-extras.csv` | Aged steaks, mince, cod, bakery extras |
| `dry-beverages.csv` | Tea, juice, portion cereals |
| `source-photos/` | Original JPEGs |

## Columns
`section, dish, item, code, supplier, notes`

- **dish** headers carry `notes=dish` (or section)
- Ingredient lines nest under dish
- Codes/suppliers as printed (OCR — verify faded cells before PO)
- Cottage pie beef/mash lines marked **hand-struck** on photo
- Sky bar focaccia swap note preserved as NOTE row

## Stats
- Total rows: **546**
- Sections: breakfast, dry-beverages, menu-mep-1, menu-mep-2, menu-mep-3, menu-mep-4, menu-mep-6, menu-mep-7-birch, proteins-extras, sky-bar

## Not done automatically
- Live catalogue / supplier_item upsert into Evolving Cook DB
- Graph-recall research-candidate journal stage
- Replacing `sheets/skybar-mep-list.csv` (different shape; sky-bar.csv is code-first)

## Next (your call)
1. Spot-check high-volume codes (Brakes/UFC/BPM)
2. Import path: purchasing SupplierItem link vs dish-template components
3. Optional graph-recall stage for house SOP


## Import status (2026-08-04 22:54 UTC)

Ran live:

```bash
python manage.py seed_catalog --sheets-only
python manage.py seed_dish_templates --alc-only
```

Sheets wired into seeders:
- `sheets/alc-dish-sheet-p3.csv` — menu MEP expansion + **15 kids dishes**
- `sheets/alc-dish-sheet-p4-catalog-extras.csv` — breakfast / dry / proteins / sky-bar SKUs (catalogue only)

### Live counts after import
| | |
|--|--|
| Items | 499 |
| SupplierItems | 397 |
| Suppliers | 24 |
| ALC dish templates | 68 (66 active; sticky pigs + crab cake inactive) |
| Kids templates | 15 (`KIDS …`) |
| Template components | 451 ALC (+ prior skybar etc. → 581 total) |

Kids dish names are prefixed **KIDS** so they do not collide with adult MAC / FISH / pizza templates.

Skybar **dish** templates still come from `skybar-mep-list.csv` (unchanged). Sky-bar SKU codes landed as catalogue Item+SupplierItem rows only.

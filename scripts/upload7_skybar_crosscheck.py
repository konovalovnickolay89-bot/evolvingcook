#!/usr/bin/env python3
"""Cross-check CatalogIngestUpload #7 proposals vs sheets/skybar-mep-list.csv."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from catalog.models import CatalogIngestProposal, CatalogIngestUpload  # noqa: E402

CSV_PATH = ROOT / "sheets" / "skybar-mep-list.csv"
OUT_DIR = Path.home() / ".hermes/profiles/linux-wiki/kanban-deliverables"
UPLOAD_ID = 7

# Common OCR confusions → preferred CSV form (for near-miss labelling)
OCR_HINTS = {
    "glazing platter": "GRAZING PLATTER",
    "glazing": "grazing",
    "nocellar olives": "Nocellara olives",
    "nocellar": "nocellara",
    "srocchiarella": "scrocchiarella",
    "butter/lettuce/balsamic glaze": "Burrata / pesto / balsamic glaze",
}


def norm(s: str) -> str:
    s = (s or "").lower().replace("'", "'").replace("'", "'")
    s = re.sub(r"[^a-z0-9+/& ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_csv(path: Path):
    components: list[dict] = []
    dishes: dict[str, list[str]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dish = (row.get("dish") or "").strip()
            comp = (row.get("component") or "").strip()
            notes = (row.get("notes") or "").strip()
            if not comp:
                continue
            components.append({"dish": dish, "component": comp, "notes": notes})
            dishes[dish].append(comp)
    return components, dishes


def best_match(name: str, csv_by_norm: dict[str, list[dict]]):
    n = norm(name)
    # apply OCR hint substitution on proposal side
    n_hint = n
    for bad, good in OCR_HINTS.items():
        if bad in n_hint:
            n_hint = n_hint.replace(bad, norm(good))

    for key in (n, n_hint):
        if key in csv_by_norm:
            return "match", csv_by_norm[key][0]["component"], 1.0, None

    best = None
    best_s = 0.0
    for cn, rows in csv_by_norm.items():
        s = SequenceMatcher(None, n_hint or n, cn).ratio()
        ta, tb = set((n_hint or n).split()), set(cn.split())
        j = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
        score = max(s, j)
        if score > best_s:
            best_s = score
            best = rows[0]["component"]

    suggested = None
    # flag classic OCR casualty
    if "glazing" in n and best and "grazing" in norm(best):
        suggested = best
    if best_s >= 0.92:
        return "match", best, best_s, suggested
    if best_s >= 0.55:
        return "near-miss", best, best_s, suggested or best
    return "not-in-CSV", best, best_s, suggested


def proposal_name(p) -> str:
    for fn in ("name", "item_name", "label"):
        if hasattr(p, fn) and getattr(p, fn):
            return str(getattr(p, fn))
    return ""


def proposal_supplier_fields(p) -> tuple[str, str]:
    supplier = ""
    code = ""
    for fn in ("supplier_name", "supplier", "proposed_supplier"):
        if hasattr(p, fn) and getattr(p, fn) not in (None, ""):
            v = getattr(p, fn)
            supplier = str(v) if not hasattr(v, "pk") else str(getattr(v, "name", v))
            break
    # FK supplier?
    if hasattr(p, "supplier_id") and p.supplier_id:
        try:
            supplier = str(p.supplier)
        except Exception:
            supplier = f"id={p.supplier_id}"
    for fn in ("supplier_code", "code", "proposed_code"):
        if hasattr(p, fn) and getattr(p, fn) not in (None, ""):
            code = str(getattr(p, fn))
            break
    return supplier, code


def main() -> int:
    u = CatalogIngestUpload.objects.get(pk=UPLOAD_ID)
    components, dishes = load_csv(CSV_PATH)
    csv_by_norm: dict[str, list[dict]] = {}
    for c in components:
        csv_by_norm.setdefault(norm(c["component"]), []).append(c)

    props = list(CatalogIngestProposal.objects.filter(upload_id=UPLOAD_ID).order_by("id"))
    results = []
    supplier_bugs = []
    match_n = near_n = miss_n = 0

    for p in props:
        name = proposal_name(p)
        supplier, code = proposal_supplier_fields(p)
        kind, matched, score, suggested = best_match(name, csv_by_norm)
        if kind == "match":
            match_n += 1
        elif kind == "near-miss":
            near_n += 1
        else:
            miss_n += 1

        inv = bool((supplier and supplier.strip()) or (code and code.strip()))
        if inv:
            supplier_bugs.append(
                {"id": p.id, "name": name, "supplier": supplier, "code": code}
            )

        rec = {
            "id": p.id,
            "proposal": name,
            "annotation": kind,
            "csv_component": matched,
            "score": round(float(score or 0), 3),
            "suggested_correction": suggested,
            "supplier": supplier,
            "supplier_code": code,
            "d8_supplier_null_ok": not inv,
            "status": getattr(p, "status", None),
        }
        results.append(rec)

    covered = {norm(r["csv_component"]) for r in results if r["annotation"] in ("match", "near-miss") and r["csv_component"]}
    uncovered = [c for c in components if norm(c["component"]) not in covered]

    total = len(props) or 1
    summary = {
        "upload_id": UPLOAD_ID,
        "upload_status": u.status,
        "image": str(u.image) if u.image else None,
        "csv": str(CSV_PATH),
        "csv_component_rows": len(components),
        "csv_dish_count": len(dishes),
        "csv_dishes": {k: len(v) for k, v in sorted(dishes.items())},
        "proposal_count": len(props),
        "hit_rate": {
            "match": match_n,
            "near_miss": near_n,
            "not_in_csv": miss_n,
            "match_pct": round(100 * match_n / total, 1),
            "match_or_near_pct": round(100 * (match_n + near_n) / total, 1),
        },
        "d8_skybar_supplier_null": {
            "rule": "Skybar MEP items: supplier should be null (D8); invented supplier/code = extraction bug",
            "ok_count": len(props) - len(supplier_bugs),
            "invented_count": len(supplier_bugs),
            "bugs": supplier_bugs,
        },
        "near_misses": [r for r in results if r["annotation"] == "near-miss"],
        "not_in_csv": [r for r in results if r["annotation"] == "not-in-CSV"],
        "csv_uncovered_count": len(uncovered),
        "csv_uncovered": uncovered,
        "note": "122 accepted items ≠ board; Phase 1.5 dish templates still owed separately",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "evolving-cook-upload7-skybar-crosscheck.json"
    md_path = OUT_DIR / "evolving-cook-upload7-skybar-crosscheck-REPORT.md"
    json_path.write_text(json.dumps({"summary": summary, "all_proposals": results}, indent=2))

    lines = [
        "# Upload #7 × skybar-mep-list.csv cross-check",
        "",
        f"**Upload:** #{UPLOAD_ID} (`{u.status}`) · image `{u.image}`  ",
        f"**CSV:** `{CSV_PATH}` · {len(components)} component rows · {len(dishes)} dishes  ",
        f"**Proposals:** {len(props)}  ",
        "",
        "## Hit-rate",
        "",
        f"| Annotation | Count | % of proposals |",
        f"|------------|------:|---------------:|",
        f"| match | {match_n} | {summary['hit_rate']['match_pct']}% |",
        f"| near-miss | {near_n} | {round(100*near_n/total,1)}% |",
        f"| not-in-CSV | {miss_n} | {round(100*miss_n/total,1)}% |",
        f"| **match + near-miss** | **{match_n+near_n}** | **{summary['hit_rate']['match_or_near_pct']}%** |",
        "",
        f"CSV components with no proposal match/near-miss: **{len(uncovered)}** / {len(components)}",
        "",
        "## D8 — supplier must be null (skybar MEP)",
        "",
        f"- OK (no supplier / code): **{summary['d8_skybar_supplier_null']['ok_count']}**",
        f"- Invented supplier or code: **{summary['d8_skybar_supplier_null']['invented_count']}**",
        "",
    ]
    if supplier_bugs:
        lines += ["| id | proposal | supplier | code |", "|----|----------|----------|------|"]
        for b in supplier_bugs:
            lines.append(
                f"| {b['id']} | {b['name']} | {b['supplier'] or '—'} | {b['code'] or '—'} |"
            )
        lines.append("")
    else:
        lines.append("No supplier/code inventions — D8 clean on this batch.")
        lines.append("")

    lines += ["## Near-misses (proposal → CSV suggestion)", ""]
    if not summary["near_misses"]:
        lines.append("_None at threshold ≥0.55._")
    else:
        lines += ["| id | proposal | csv / suggested | score |", "|----|----------|-----------------|------:|"]
        for r in summary["near_misses"]:
            sug = r.get("suggested_correction") or r.get("csv_component") or ""
            lines.append(
                f"| {r['id']} | {r['proposal']} | {sug} | {r['score']} |"
            )
    lines += ["", "## not-in-CSV proposals", ""]
    if not summary["not_in_csv"]:
        lines.append("_None._")
    else:
        lines += ["| id | proposal | best csv (score) |", "|----|----------|------------------|"]
        for r in summary["not_in_csv"]:
            lines.append(
                f"| {r['id']} | {r['proposal']} | {r.get('csv_component') or '—'} ({r['score']}) |"
            )

    lines += [
        "",
        "## CSV uncovered (no proposal hit)",
        "",
    ]
    if not uncovered:
        lines.append("_All CSV components covered by match or near-miss._")
    else:
        lines += ["| dish | component | notes |", "|------|-----------|-------|"]
        for c in uncovered:
            lines.append(f"| {c['dish']} | {c['component']} | {c['notes']} |")

    lines += [
        "",
        "## Notable OCR casualties",
        "",
        "- Watch for **Glazing platter** → **GRAZING PLATTER** (classic).",
        "- Admin remains the review surface; do not bulk-accept without reading near-misses.",
        "",
        "## Separate debt (not this job)",
        "",
        "Phase 1.5 skybar **dish templates** from CSV dish→component structure — "
        "accepted items ≠ board lines. Seed re-runnably; report line counts per dish.",
        "",
        f"JSON: `{json_path}`",
        "",
    ]
    md_path.write_text("\n".join(lines))
    print(json.dumps(summary["hit_rate"], indent=2))
    print("d8_invented", len(supplier_bugs))
    print("uncovered", len(uncovered))
    print("md", md_path)
    print("json", json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

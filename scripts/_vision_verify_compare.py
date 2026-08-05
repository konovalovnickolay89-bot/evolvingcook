#!/usr/bin/env python3
"""Compare CatalogIngestProposal rows to ALC CSV ground truth (t_0d8c113b)."""
from __future__ import annotations

import csv
import os
import re
import sys
import unicodedata
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
django.setup()

from catalog.models import CatalogIngestProposal, CatalogIngestUpload  # noqa: E402

UPLOAD_ID = 6
CSV_PATH = Path("/home/discovery-system/src/evolving-cook/sheets/alc-dish-sheet-p1.csv")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.casefold().strip()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[\s,;/|]+", " ", s)
    s = re.sub(r"[^a-z0-9&+.\- ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def codes_of(raw: str) -> set[str]:
    """Split dual codes like '112724 / 591085' into normalized tokens."""
    if not raw:
        return set()
    parts = re.split(r"[/,|;]+|\s+or\s+", raw, flags=re.I)
    out = set()
    for p in parts:
        t = re.sub(r"\s+", "", p).casefold()
        t = re.sub(r"[^a-z0-9]", "", t)
        if t:
            out.add(t)
    return out


def name_match(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # allow containment if both long enough
    if len(na) >= 6 and len(nb) >= 6 and (na in nb or nb in na):
        return True
    # token overlap (Jaccard) for fuzzy
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union >= 0.6 and inter >= 2


def main() -> None:
    u = CatalogIngestUpload.objects.get(pk=UPLOAD_ID)
    props = list(u.proposals.all())
    print(
        f"upload={u.id} status={u.status} model={u.model_name!r} "
        f"source={u.source_kind} proposals={len(props)} image={u.image.name}"
    )

    rows = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not (r.get("item") or "").strip() and not (r.get("supplier_code") or "").strip():
                continue
            rows.append(r)
    print(f"csv_rows={len(rows)} path={CSV_PATH}")

    prop_codes: set[str] = set()
    prop_names = [p.name for p in props]
    prop_by_code: dict[str, list] = {}
    for p in props:
        for c in codes_of(p.supplier_code):
            prop_codes.add(c)
            prop_by_code.setdefault(c, []).append(p)

    csv_codes: set[str] = set()
    matched_code_rows = 0
    matched_name_rows = 0
    matched_both = 0
    matched_supplier = 0
    missing = []
    details = []

    for r in rows:
        item = (r.get("item") or "").strip()
        sc = (r.get("supplier_code") or "").strip()
        sup = (r.get("supplier") or "").strip()
        dish = (r.get("dish") or "").strip()
        cset = codes_of(sc)
        csv_codes |= cset
        code_hit = bool(cset & prop_codes)
        name_hit = any(name_match(item, pn) for pn in prop_names)
        # supplier: any proposal that matched code or name has similar supplier
        sup_hit = False
        candidates = []
        if code_hit:
            for c in cset:
                candidates.extend(prop_by_code.get(c, []))
        if not candidates:
            candidates = [p for p in props if name_match(item, p.name)]
        for p in candidates:
            if norm(sup) and (norm(sup) in norm(p.supplier_name) or norm(p.supplier_name) in norm(sup)):
                sup_hit = True
                break
            # partial supplier tokens
            if norm(sup) and norm(p.supplier_name):
                st, pt = set(norm(sup).replace("/", " ").split()), set(norm(p.supplier_name).split())
                if st & pt:
                    sup_hit = True
                    break
        if code_hit:
            matched_code_rows += 1
        if name_hit:
            matched_name_rows += 1
        if code_hit and name_hit:
            matched_both += 1
        if sup_hit:
            matched_supplier += 1
        if not code_hit:
            missing.append((dish, item, sc, sup, "code_miss", name_hit, sup_hit))
        details.append((dish, item, sc, sup, code_hit, name_hit, sup_hit))

    # false extras: proposal codes not in csv
    false_extra_codes = sorted(prop_codes - csv_codes)
    # proposals with no name match to any csv item
    unmatched_props = []
    for p in props:
        if not any(name_match(p.name, r.get("item") or "") for r in rows):
            unmatched_props.append(p)

    # Anchor
    anchor_code = "5003923"
    anchor_name_bits = ("focaccia", "scrocchiarella")
    anchor_sup = "brakes"
    anchor_code_hit = anchor_code in prop_codes
    anchor_props = prop_by_code.get(anchor_code, [])
    anchor_name_hit = any(
        "focaccia" in norm(p.name) or "scrocchiarella" in norm(p.name) for p in props
    ) or any(
        all(b in norm(p.name) for b in anchor_name_bits) for p in props
    )
    # looser name
    if not anchor_name_hit:
        anchor_name_hit = any("focaccia" in norm(p.name) for p in props)
    anchor_sup_hit = any(anchor_sup in norm(p.supplier_name) for p in anchor_props) or any(
        anchor_sup in norm(p.supplier_name) and ("focaccia" in norm(p.name) or "scrocchiarella" in norm(p.name))
        for p in props
    )
    anchor = "HIT" if (anchor_code_hit and anchor_name_hit) else "MISS"

    print("=== HIT RATES (row-level vs p1 CSV) ===")
    print(f"csv_item_rows={len(rows)}")
    print(f"matched_codes_rows={matched_code_rows}/{len(rows)}")
    print(f"matched_names_rows={matched_name_rows}/{len(rows)}")
    print(f"matched_both_code_and_name={matched_both}/{len(rows)}")
    print(f"matched_supplier_on_candidates={matched_supplier}/{len(rows)}")
    print(f"unique_csv_codes={len(csv_codes)} unique_prop_codes={len(prop_codes)}")
    print(f"prop_codes_in_csv={len(prop_codes & csv_codes)} false_extra_codes={len(false_extra_codes)}")
    print(f"unmatched_proposal_names={len(unmatched_props)}/{len(props)}")
    print(f"ANCHOR Focaccia/5003923/BRAKES: {anchor}")
    print(f"  code_hit={anchor_code_hit} name_hit={anchor_name_hit} supplier_hit={anchor_sup_hit}")
    if anchor_props:
        for p in anchor_props:
            print(f"  prop id={p.id} name={p.name!r} code={p.supplier_code!r} sup={p.supplier_name!r} dish={p.dish!r} status={p.status}")
    else:
        # show focaccia-ish
        for p in props:
            if "focaccia" in norm(p.name) or "scrocch" in norm(p.name) or "5003923" in (p.supplier_code or ""):
                print(f"  near id={p.id} name={p.name!r} code={p.supplier_code!r} sup={p.supplier_name!r}")

    print("=== MISSING CODE ROWS (up to 25) ===")
    for m in missing[:25]:
        print(m)
    print("=== FALSE EXTRA CODES (up to 30) ===")
    print(false_extra_codes[:30])
    print("=== SAMPLE PROPOSALS (first 15) ===")
    for p in props[:15]:
        print(p.id, p.status, p.dish[:40], "|", p.name[:40], "|", p.supplier_code, "|", p.supplier_name)
    print("=== ALL PROPOSALS STATUS COUNTS ===")
    from collections import Counter
    print(Counter(p.status for p in props))


if __name__ == "__main__":
    main()

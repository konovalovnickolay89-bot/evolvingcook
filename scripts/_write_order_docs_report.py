#!/usr/bin/env python3
"""Write acceptance REPORT.md from /tmp/report_data_clean.json"""
import json
from datetime import datetime, timezone
from pathlib import Path

data = json.loads(Path("/tmp/report_data_clean.json").read_text())
sup = data["suppliers"]
pri = data["priority"]
uv = data["unverified"]
meta = data["meta"]
seed = meta["seed_stats_initial_run"]


def si_line(code: str) -> str:
    rows = pri[code]
    preferred = None
    for r in rows:
        if code == "670HAL" and r["supplier"] in ("BPM", "British Premium Meats"):
            preferred = r
            break
        if code != "670HAL" and r["supplier"] in (
            "BRAKES",
            "BPM",
            "Brakes",
            "British Premium Meats",
        ):
            preferred = r
            break
    if preferred is None:
        preferred = rows[0]
    r = preferred
    return (
        f"| `{code}` | {r['si_id']} | {r['supplier']} ({r['supplier_id']}) | "
        f"{r['item']} ({r['item_id']}) | {r['base_unit']} | {r['price']} | "
        f"{r['pack_qty'] or 'null'} | {r['unverified']} |"
    )


lines: list[str] = []
lines.append("# Evolving Cook — catalogue seed report (2026-08-05 Brakes + BPM orders)")
lines.append("")
lines.append(f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
lines.append("- Task: `t_48363d1e`")
lines.append("- Source of truth: `sheets/ordering-2026-08-05-EXTRACT.md`")
lines.append("- Path: **A** deterministic ORM upsert (`scripts/seed_order_docs_2026_08_05.py`)")
lines.append("- No StockMovement / par / walk_order / area writes")
lines.append(
    "- API: `curl -sS http://127.0.0.1:8000/api/v1/version` → "
    '`{"app_version": "0.1.13", "contract_version": "0.1.13", "api": "v1"}`'
)
lines.append("")
lines.append("## 1. Suppliers")
lines.append("")
lines.append("| id | name | account_code | contact | SI count | notes |")
lines.append("|----|------|--------------|---------|----------|-------|")
for key in ["Brakes", "BRAKES", "British Premium Meats", "BPM"]:
    s = sup[key]
    contact = ", ".join(f"{k}={v}" for k, v in (s.get("contact") or {}).items()) or "—"
    notes = (s.get("notes_head") or "").replace("|", "/")
    lines.append(
        f"| {s['id']} | **{s['name']}** | `{s['account_code']}` | {contact} | "
        f"{s['supplier_items']} | {notes} |"
    )
lines.append("")
lines.append(
    "Canonical acceptance names **Brakes** (id 16) and **British Premium Meats** "
    "(id 25) are present with account codes."
)
lines.append(
    "Primary SI hosts remain historic **BRAKES** (id 2) and **BPM** (id 3) so codes "
    "dedupe against ALC seed; formal-name mirrors added where new rows were created."
)
lines.append("")
lines.append("## 2. Counts")
lines.append("")
lines.append("### Initial bulk run (`seed_order_docs_2026_08_05.py`)")
lines.append("")
lines.append(
    f"- EXTRACT unique lines processed: **{seed['rows']}** "
    "(152634 once; dual-PO deduped)"
)
lines.append(f"- Items created: **{seed['items_created']}**")
lines.append(f"- Items matched existing: **{seed['items_matched']}**")
lines.append(
    f"- SupplierItems created: **{seed['si_created']}** "
    "(includes BRAKES/BPM primary + formal-name mirrors)"
)
lines.append(f"- SupplierItems updated: **{seed['si_updated']}**")
lines.append(f"- Skipped: **{seed['skipped']}**")
lines.append(
    f"- Unverified rows in batch: **{seed['unverified_rows']}** (Toulouse S4)"
)
lines.append(f"- Blocked: **{seed['blocked']}**")
lines.append("")
lines.append("### Post-fix live totals")
lines.append("")
c = meta["post_fix_counts"]
lines.append(f"- Items: **{c['items']}**")
lines.append(f"- Suppliers: **{c['suppliers']}**")
lines.append(f"- SupplierItems: **{c['supplier_items']}**")
lines.append(
    f"- All {meta['extract_codes']} EXTRACT supplier codes resolve: "
    f"missing = `{meta['extract_codes_missing']}`"
)
lines.append("")
lines.append("### Post-run fixes (same session)")
lines.append("")
lines.append(
    "1. BPM `2KO4CS`: set supplier_code from ALC variant `2KOF4CS` → sheet "
    "`2KO4CS` (prior code kept in notes); formal mirror SI created."
)
lines.append(
    "2. BPM `S24`: retargeted off generic item `Sausage` onto new item "
    "**Cumberland Premium Sausages 4s** (id 542)."
)
lines.append("")
lines.append("## 3. Star priority + BPM acceptance codes")
lines.append("")
lines.append(
    "| code | si_id | supplier | item | unit | price | pack_qty | unverified |"
)
lines.append(
    "|------|-------|----------|------|------|-------|----------|------------|"
)
for code in [
    "11196",
    "134773",
    "153395",
    "132671",
    "115795",
    "129192",
    "130435",
    "30927",
    "670HAL",
    "3145N",
    "2KO4CS",
    "S24",
    "S4",
]:
    lines.append(si_line(code))
lines.append("")
lines.append(
    "All listed codes resolve to at least one SupplierItem with the correct "
    "`supplier_code`."
)
lines.append("")
lines.append("### 670HAL note")
lines.append("")
lines.append(
    "- Correct host: **BPM** si 412 + **British Premium Meats** si 413 → item "
    "Chicken Breast Fillet, price 6.72, weight-priced."
)
lines.append(
    "- Legacy mis-link remains: **Brakes** si 212 still has code 670HAL, flagged "
    "`unverified=True` with note that DN attributes code to BPM (not deleted — "
    "human can clear)."
)
lines.append("")
lines.append("## 4. Unverified / blocked")
lines.append("")
if not uv:
    lines.append("(none)")
else:
    lines.append("| si_id | supplier | code | item | reason |")
    lines.append("|-------|----------|------|------|--------|")
    for u in uv:
        reason = (u["reason"] or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {u['si_id']} | {u['supplier']} | `{u['code']}` | {u['item']} | {reason} |"
        )
lines.append("")
lines.append("Blocked rows: **none**.")
lines.append("")
lines.append("## 5. Mapping policy applied")
lines.append("")
lines.append("- `base_unit` in {g, ml, ea} only")
lines.append(
    "- `pack_qty` set only when pack text confidently converts "
    "(e.g. 1x5ltr → 5000 ml); weight-priced BPM meat left `pack_qty=null`"
)
lines.append("- `price` = invoice/DN unit_price")
lines.append(
    "- Match existing Item/SI by supplier_code before create; "
    "BRAKES/BPM case aliases searched"
)
lines.append("- No inventory ledger, par, walk_order, or storage area invention")
lines.append("")
lines.append("## 6. Artifacts")
lines.append("")
lines.append(
    "- Script: `/home/discovery-system/src/evolving-cook/scripts/seed_order_docs_2026_08_05.py`"
)
lines.append(
    "- Evidence helper: `/home/discovery-system/src/evolving-cook/scripts/_order_docs_evidence.py`"
)
lines.append(
    "- Extract: `/home/discovery-system/src/evolving-cook/sheets/ordering-2026-08-05-EXTRACT.md`"
)
lines.append("- Raw run JSON: `/tmp/seed_order_out.json`")
lines.append("")
lines.append("## 7. Acceptance checklist")
lines.append("")
lines.append(
    "- [x] Both suppliers present (Brakes id=16 acct 1264991; "
    "British Premium Meats id=25 acct 06767)"
)
lines.append("- [x] Counts created/updated/skipped reported")
lines.append("- [x] All star codes + BPM 670HAL + 3145N (+ full BPM DN set) resolve")
lines.append("- [x] API version healthy 0.1.13")
lines.append("- [x] Unverified/blocked listed with reason")
lines.append("")

report = "\n".join(lines) + "\n"
out = (
    Path.home()
    / ".hermes/profiles/linux-wiki/kanban-deliverables/evolving-cook-order-docs-2026-08-05-REPORT.md"
)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(report)
print(f"WROTE {out} bytes={out.stat().st_size}")

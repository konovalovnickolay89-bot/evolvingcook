"""Rewrite stored allergen names onto the UK 14 allowlist.

Idempotent. Rows are updated in place; nothing is deleted. Legacy aliases
(gluten, nuts, soy, …) become the canonical name. Tokens that are not a
recognised name or alias are removed — they are not allergen names, and
leaving them would keep reading as a recorded allergen. Empty stays empty
(allergens not recorded). Reverse is a no-op: canonical names are valid
for the previous column type, and dropped tokens are not restored.
"""

from django.db import migrations


def _as_list(raw):
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return []


def forwards(apps, schema_editor):
    from catalog.allergens import normalize_allergens

    for model in (
        apps.get_model("catalog", "Recipe"),
        apps.get_model("catalog", "Item"),
    ):
        for row in model.objects.all().iterator():
            raw = row.allergens
            raw_list = _as_list(raw)
            normalised = normalize_allergens(raw_list, strict=False)
            if isinstance(raw, (list, tuple)) and raw_list == normalised:
                continue
            # QuerySet.update skips Model.save so a later save() hook cannot
            # hide a migration that forgot to normalise.
            model.objects.filter(pk=row.pk).update(allergens=normalised)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0004_ingest_propose_requested"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

# D17 — recipe cards (production spec + method)

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_d12_notes_house_made"),
    ]

    operations = [
        migrations.CreateModel(
            name="Recipe",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("section", models.CharField(blank=True, default="", max_length=32)),
                ("base_covers", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "yield_qty",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=18, null=True
                    ),
                ),
                ("yield_unit", models.CharField(blank=True, default="", max_length=32)),
                ("ingredients", models.JSONField(blank=True, default=list)),
                ("method", models.JSONField(blank=True, default=list)),
                ("allergens", models.JSONField(blank=True, default=list)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "source",
                    models.CharField(
                        choices=[("chef", "Chef"), ("companion", "Companion")],
                        default="chef",
                        max_length=16,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name", "id"],
            },
        ),
    ]

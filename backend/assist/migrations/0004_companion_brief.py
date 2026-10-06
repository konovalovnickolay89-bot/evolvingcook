# D16 — companion daily brief cache

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assist", "0003_station_log_intelligence"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanionBrief",
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
                ("service_date", models.DateField(db_index=True, unique=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("model", models.CharField(blank=True, default="", max_length=128)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-service_date"],
            },
        ),
    ]

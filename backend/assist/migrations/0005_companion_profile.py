# D16 — companion house profile (chef's standing rules)

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assist", "0004_companion_brief"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanionProfile",
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
                ("singleton", models.BooleanField(default=True, unique=True)),
                ("text", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]

# Generated manually for D15 SectionSetting

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("planning", "0003_phase4_full_planner"),
    ]

    operations = [
        migrations.CreateModel(
            name="SectionSetting",
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
                (
                    "section",
                    models.CharField(
                        choices=[
                            ("breakfast_buffet", "Breakfast buffet"),
                            ("a_la_carte", "A la carte"),
                            ("banquet_buffet", "Banquet buffet"),
                            ("banqueting", "Banqueting"),
                            ("canteen", "Canteen"),
                            ("skybar", "Skybar"),
                        ],
                        db_index=True,
                        max_length=32,
                        unique=True,
                    ),
                ),
                (
                    "mode",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("counts", "Counts matter"),
                            ("ordering", "Just ordering"),
                        ],
                        help_text="null until chef answers the mode prompt",
                        max_length=16,
                        null=True,
                    ),
                ),
                (
                    "guided",
                    models.BooleanField(
                        default=False,
                        help_text="Guided prep plan (banqueting defaults true)",
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "section setting",
                "verbose_name_plural": "section settings",
                "ordering": ["section"],
            },
        ),
    ]

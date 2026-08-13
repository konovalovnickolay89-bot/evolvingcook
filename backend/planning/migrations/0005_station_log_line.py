# Generated for StationLogLine

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_d12_notes_house_made"),
        ("planning", "0004_section_setting"),
    ]

    operations = [
        migrations.CreateModel(
            name="StationLogLine",
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
                    "kind",
                    models.CharField(
                        choices=[
                            ("mep", "Mise en place"),
                            ("house_prep", "House prep"),
                            ("service", "Service"),
                            ("holding", "Holding and storage"),
                            ("leftover", "Leftovers"),
                            ("cook_priority", "Cooking priority"),
                            ("expire_soon", "Expire soon"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("text", models.CharField(max_length=500)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("check", "Check"),
                            ("order", "Order"),
                            ("prep", "Prep"),
                            ("hold", "Hold"),
                            ("none", "None"),
                        ],
                        default="none",
                        max_length=16,
                    ),
                ),
                (
                    "qty",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=18, null=True
                    ),
                ),
                ("unit", models.CharField(blank=True, default="", max_length=16)),
                ("use_by", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Open"), ("done", "Done")],
                        db_index=True,
                        default="open",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("chef", "Chef"),
                            ("suggest", "Suggest"),
                            ("carried", "Carried"),
                        ],
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
                ("done_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "area",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="station_log_lines",
                        to="catalog.storagearea",
                    ),
                ),
                (
                    "carried_from",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="carried_to",
                        to="planning.stationlogline",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="station_log_lines",
                        to="catalog.item",
                    ),
                ),
                (
                    "line",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="station_log_lines",
                        to="planning.productionline",
                    ),
                ),
                (
                    "service_section",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="log_lines",
                        to="planning.servicesection",
                    ),
                ),
            ],
            options={
                "ordering": ["kind", "status", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="stationlogline",
            index=models.Index(
                fields=["service_section", "status"],
                name="planning_st_service_3b8c1a_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="stationlogline",
            index=models.Index(
                fields=["service_section", "kind"],
                name="planning_st_service_9c2e4d_idx",
            ),
        ),
    ]

# station_log job kind + IntelligenceAssignment

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assist", "0002_d15_job_kinds"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assistjob",
            name="kind",
            field=models.CharField(
                choices=[
                    ("parse_note", "parse_note"),
                    ("prep_plan", "prep_plan"),
                    ("menu_completeness", "menu_completeness"),
                    ("order_suggest", "order_suggest"),
                    ("qty_draft", "qty_draft"),
                    ("morning_qty", "morning_qty"),
                    ("station_log", "station_log"),
                ],
                db_index=True,
                max_length=64,
            ),
        ),
        migrations.CreateModel(
            name="IntelligenceAssignment",
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
                    "task",
                    models.CharField(
                        choices=[("station_log", "station_log")],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("rules", "rules"),
                            ("hermes", "hermes"),
                            ("grok", "grok"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "section",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["task", "section"]},
        ),
        migrations.AddConstraint(
            model_name="intelligenceassignment",
            constraint=models.UniqueConstraint(
                fields=("task", "section"),
                name="uniq_intelligenceassignment_task_section",
            ),
        ),
    ]

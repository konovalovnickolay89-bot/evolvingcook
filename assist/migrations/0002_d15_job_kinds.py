# D15 expand AssistJob kinds for section-mode gated jobs

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assist", "0001_phase5_assist"),
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
                ],
                db_index=True,
                max_length=64,
            ),
        ),
    ]

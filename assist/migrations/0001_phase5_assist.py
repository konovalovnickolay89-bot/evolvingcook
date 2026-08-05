# Generated manually for Phase 5 AssistJob + AssistProposal

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AssistJob",
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
                        choices=[("parse_note", "parse_note")],
                        db_index=True,
                        max_length=64,
                    ),
                ),
                ("context", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="queued",
                        max_length=16,
                    ),
                ),
                (
                    "task_id",
                    models.CharField(
                        blank=True, max_length=128, null=True, unique=True
                    ),
                ),
                ("error", models.TextField(blank=True, default="")),
                (
                    "q_task_id",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="django-q2 async_task id when enqueued",
                        max_length=64,
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
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="AssistProposal",
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
                ("kind", models.CharField(db_index=True, max_length=64)),
                ("context", models.JSONField(blank=True, default=dict)),
                ("proposal", models.JSONField(blank=True, default=dict)),
                ("rationale", models.TextField(blank=True, default="")),
                ("model", models.CharField(blank=True, default="", max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("accepted", "Accepted"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("reject_reason", models.TextField(blank=True, default="")),
                (
                    "task_id",
                    models.CharField(
                        blank=True, max_length=128, null=True, unique=True
                    ),
                ),
                (
                    "parse_error",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Set when agent text was not valid JSON; proposal may be empty.",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="proposals",
                        to="assist.assistjob",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]

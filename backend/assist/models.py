"""
Assist domain (Phase 5) — AssistJob + AssistProposal.

Webhook completion upserts proposals only; accept handlers write domain state.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class AssistJob(models.Model):
    """Outbound A2A task lifecycle (django-q2 worker enqueues SendMessage)."""

    class Kind(models.TextChoices):
        PARSE_NOTE = "parse_note", "parse_note"
        PREP_PLAN = "prep_plan", "prep_plan"
        MENU_COMPLETENESS = "menu_completeness", "menu_completeness"
        ORDER_SUGGEST = "order_suggest", "order_suggest"
        QTY_DRAFT = "qty_draft", "qty_draft"
        MORNING_QTY = "morning_qty", "morning_qty"
        STATION_LOG = "station_log", "station_log"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    kind = models.CharField(max_length=64, choices=Kind.choices, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    # A2A task id from Hermes — unique when set
    task_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    error = models.TextField(blank=True, default="")
    q_task_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="django-q2 async_task id when enqueued",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"AssistJob#{self.pk} {self.kind} {self.status}"


class AssistProposal(models.Model):
    """
    LLM / A2A proposal only — never domain state until accept handler runs.
    Idempotent on task_id for webhook redelivery.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    kind = models.CharField(max_length=64, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    proposal = models.JSONField(default=dict, blank=True)
    rationale = models.TextField(blank=True, default="")
    model = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")
    # A2A task id — unique when set (Hermes natural key)
    task_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    job = models.ForeignKey(
        AssistJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="proposals",
    )
    parse_error = models.TextField(
        blank=True,
        default="",
        help_text="Set when agent text was not valid JSON; proposal may be empty.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"AssistProposal#{self.pk} {self.kind} {self.status}"


class IntelligenceAssignment(models.Model):
    """
    Programmatic provider assignment. No chef-facing picker.
    section null = default for the task. Per-section row overrides.
    """

    class Task(models.TextChoices):
        STATION_LOG = "station_log", "station_log"

    class Provider(models.TextChoices):
        RULES = "rules", "rules"
        HERMES = "hermes", "hermes"
        GROK = "grok", "grok"

    task = models.CharField(max_length=32, choices=Task.choices, db_index=True)
    provider = models.CharField(max_length=32, choices=Provider.choices)
    section = models.CharField(max_length=32, blank=True, default="", db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "section"],
                name="uniq_intelligenceassignment_task_section",
            ),
        ]
        ordering = ["task", "section"]

    def __str__(self) -> str:
        sec = self.section or "*"
        return f"{self.task}@{sec}={self.provider}"


class CompanionBrief(models.Model):
    """D16 — cached companion daily brief; one row per service date."""

    service_date = models.DateField(unique=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-service_date"]

    def __str__(self) -> str:
        return f"CompanionBrief {self.service_date}"

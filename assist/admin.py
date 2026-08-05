"""Admin for AssistJob + AssistProposal (bulk accept/reject)."""
from __future__ import annotations

from django.contrib import admin, messages
from django.db import transaction

from assist.models import AssistJob, AssistProposal
from assist.services import (
    AssistError,
    accept_assist_proposal,
    enqueue_assist_job,
    reject_assist_proposal,
)


@admin.register(AssistJob)
class AssistJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "status",
        "task_id",
        "q_task_id",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("task_id", "q_task_id", "error")
    readonly_fields = ("created_at", "updated_at", "task_id", "q_task_id")
    actions = ("requeue_selected",)

    @admin.action(description="Re-enqueue selected jobs (new A2A send)")
    def requeue_selected(self, request, queryset):
        ok = err = 0
        for job in queryset:
            try:
                enqueue_assist_job(job.kind, job.context if isinstance(job.context, dict) else {})
                ok += 1
            except Exception as exc:  # noqa: BLE001
                err += 1
                self.message_user(request, f"Job #{job.pk}: {exc}", messages.ERROR)
        self.message_user(
            request,
            f"Enqueued {ok}; errors {err}.",
            messages.SUCCESS if ok else messages.WARNING,
        )


@admin.register(AssistProposal)
class AssistProposalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "status",
        "task_id",
        "job",
        "model",
        "decided_at",
        "created_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("task_id", "rationale", "reject_reason", "parse_error")
    readonly_fields = (
        "decided_at",
        "created_at",
        "updated_at",
        "task_id",
        "parse_error",
    )
    actions = ("accept_selected", "reject_selected")

    @admin.action(description="Accept → domain writes (parse_note)")
    def accept_selected(self, request, queryset):
        ok = err = 0
        for prop in queryset:
            try:
                with transaction.atomic():
                    accept_assist_proposal(prop.pk)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                err += 1
                self.message_user(
                    request,
                    f"Proposal #{prop.pk}: {exc}",
                    messages.ERROR,
                )
        self.message_user(
            request,
            f"Accepted {ok}; errors {err}.",
            messages.SUCCESS if ok else messages.WARNING,
        )

    @admin.action(description="Reject selected proposals")
    def reject_selected(self, request, queryset):
        ok = 0
        for prop in queryset:
            try:
                reject_assist_proposal(prop.pk, reason="admin bulk reject")
                ok += 1
            except AssistError as exc:
                self.message_user(
                    request,
                    f"Proposal #{prop.pk}: {exc}",
                    messages.ERROR,
                )
        self.message_user(request, f"Rejected {ok}.", messages.SUCCESS)

"""Reap AssistJob rows stuck in running without a terminal push."""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from assist.models import AssistJob


class Command(BaseCommand):
    help = "Mark AssistJob running longer than --minutes as failed (stale A2A)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=15,
            help="Age threshold in minutes (default 15)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List only; do not update",
        )

    def handle(self, *args, **options):
        minutes = max(1, int(options["minutes"]))
        dry = bool(options["dry_run"])
        cutoff = timezone.now() - timedelta(minutes=minutes)
        qs = AssistJob.objects.filter(
            status=AssistJob.Status.RUNNING,
            updated_at__lt=cutoff,
        ).order_by("id")
        n = 0
        for job in qs:
            n += 1
            msg = (
                f"stale_running: no terminal push within {minutes}m "
                f"(updated_at={job.updated_at.isoformat()})"
            )
            self.stdout.write(f"J#{job.pk} task={job.task_id} {msg}")
            if not dry:
                job.status = AssistJob.Status.FAILED
                job.error = msg[:2000]
                job.save(update_fields=["status", "error", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"reaped={n} dry_run={dry}"))

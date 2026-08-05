"""Unit tests for NOTE→ASSIST transport hardening (B1) + BE-1..4."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from assist.services import (
    enqueue_assist_job,
    handle_agent_event,
    is_agent_transport_error,
    normalize_proposal_targets,
    parse_proposal_json,
    proposal_out_dict,
    reject_assist_proposal,
)


class TransportErrorTests(TestCase):
    def test_is_agent_transport_error_markers(self):
        self.assertTrue(is_agent_transport_error(""))
        self.assertTrue(is_agent_transport_error("   "))
        self.assertTrue(
            is_agent_transport_error("⚠️ Couldn't deliver the audio attachment.")
        )
        self.assertTrue(
            is_agent_transport_error("prefix\nCouldn't deliver the audio attachment.")
        )
        self.assertFalse(
            is_agent_transport_error(
                '{"note":"x","target":"line","target_confidence":"high"}'
            )
        )

    def test_parse_json_ok(self):
        body, err = parse_proposal_json(
            '{"note":"panko today","target":"line","target_confidence":"high"}'
        )
        self.assertEqual(err, "")
        self.assertEqual(body["note"], "panko today")


class HandleAgentEventTransportTests(TestCase):
    def _payload(self, task_id: str, text: str, state: str = "TASK_STATE_COMPLETED"):
        return {
            "statusUpdate": {
                "taskId": task_id,
                "contextId": "",
                "status": {
                    "state": state,
                    "message": {"parts": [{"text": text}]},
                },
            }
        }

    def test_audio_warning_fails_job_no_proposal(self):
        job = AssistJob.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "use panko today for mac top"},
            status=AssistJob.Status.RUNNING,
            task_id="task-audio-1",
        )
        out = handle_agent_event(
            self._payload(
                "task-audio-1",
                "⚠️ Couldn't deliver the audio attachment.",
            )
        )
        job.refresh_from_db()
        self.assertEqual(out["action"], "agent_transport_error")
        self.assertEqual(job.status, AssistJob.Status.FAILED)
        self.assertEqual(
            AssistProposal.objects.filter(task_id="task-audio-1").count(), 0
        )

    def test_valid_json_creates_pending(self):
        job = AssistJob.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "use panko today for mac top", "line_id": 1},
            status=AssistJob.Status.RUNNING,
            task_id="task-ok-1",
        )
        text = (
            '{"note":"panko today","target":"line",'
            '"target_confidence":"high","components":[]}'
        )
        out = handle_agent_event(self._payload("task-ok-1", text))
        job.refresh_from_db()
        self.assertEqual(out["action"], "created")
        self.assertEqual(job.status, AssistJob.Status.SUCCEEDED)
        p = AssistProposal.objects.get(task_id="task-ok-1")
        self.assertEqual(p.status, AssistProposal.Status.PENDING)
        self.assertEqual(p.proposal.get("note"), "panko today")
        self.assertFalse(p.parse_error)


class NormalizeProposalAuditTests(TestCase):
    """BE-2: pipeline notes in proposal.audit, not rationale."""

    def test_defaulted_target_goes_to_audit(self):
        body = normalize_proposal_targets(
            {"note": "hold back", "rationale": "chef said so"}
        )
        self.assertEqual(body["target"], "line")
        self.assertEqual(body["target_confidence"], "low")
        self.assertEqual(body["rationale"], "chef said so")
        codes = [e["code"] for e in body.get("audit") or []]
        self.assertIn("defaulted_target", codes)
        self.assertNotIn("defaulted target", (body.get("rationale") or "").lower())

    def test_template_house_made_coerces_to_item_audit(self):
        body = normalize_proposal_targets(
            {
                "note": "we make this",
                "target": "template",
                "house_made": True,
                "rationale": "identity",
            }
        )
        self.assertEqual(body["target"], "item")
        self.assertEqual(body["target_confidence"], "low")
        self.assertEqual(body["rationale"], "identity")
        codes = [e["code"] for e in body.get("audit") or []]
        self.assertIn("coerced_template_to_item", codes)


class RejectReasonTests(TestCase):
    """BE-1: empty reject reason → other."""

    def test_empty_reason_defaults_other(self):
        p = AssistProposal.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "x" * 20},
            proposal={"note": "x", "target": "line", "target_confidence": "high"},
            status=AssistProposal.Status.PENDING,
        )
        out = reject_assist_proposal(p.pk, reason="")
        self.assertEqual(out.status, AssistProposal.Status.REJECTED)
        self.assertEqual(out.reject_reason, "other")

    def test_whitespace_reason_defaults_other(self):
        p = AssistProposal.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "y" * 20},
            proposal={"note": "y", "target": "line", "target_confidence": "high"},
            status=AssistProposal.Status.PENDING,
        )
        out = reject_assist_proposal(p.pk, reason="   ")
        self.assertEqual(out.reject_reason, "other")

    def test_explicit_reason_kept(self):
        p = AssistProposal.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "z" * 20},
            proposal={"note": "z", "target": "line", "target_confidence": "high"},
            status=AssistProposal.Status.PENDING,
        )
        out = reject_assist_proposal(p.pk, reason="wrong tier")
        self.assertEqual(out.reject_reason, "wrong tier")


class ProposalOutTopLevelTargetTests(TestCase):
    """BE-4: target + target_confidence on ProposalOut."""

    def test_proposal_out_surfaces_target_fields(self):
        p = AssistProposal.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "a" * 20, "line_id": 9},
            proposal={
                "note": "today only",
                "target": "line",
                "target_confidence": "high",
                "rationale": "time-bounded",
            },
            rationale="time-bounded",
            status=AssistProposal.Status.PENDING,
        )
        d = proposal_out_dict(p)
        self.assertEqual(d["target"], "line")
        self.assertEqual(d["target_confidence"], "high")
        self.assertTrue(d["accept_able"])


@override_settings(ASSIST_NOTE_DEDUPE_SECONDS=3600)
class EnqueueDedupeTests(TestCase):
    """BE-3: text_hash dedupe inside enqueue_assist_job."""

    @patch("django_q.tasks.async_task", return_value="q-fake")
    def test_second_identical_parse_note_returns_same_job(self, _async):
        # no line_id — avoids needing ProductionLine fixture; hash still set
        ctx = {"text": "use panko today for mac top unique-dedupe-a"}
        j1 = enqueue_assist_job("parse_note", ctx)
        j2 = enqueue_assist_job("parse_note", dict(ctx))
        self.assertEqual(j1.pk, j2.pk)
        self.assertEqual(
            AssistJob.objects.filter(
                kind=AssistJob.Kind.PARSE_NOTE,
                context__text_hash=j1.context.get("text_hash"),
            ).count(),
            1,
        )
        self.assertIn("text_hash", j1.context)

    @patch("django_q.tasks.async_task", return_value="q-fake")
    def test_failed_job_does_not_block_retry(self, _async):
        ctx = {"text": "retryable note text xx unique-dedupe-b"}
        j1 = enqueue_assist_job("parse_note", ctx)
        j1.status = AssistJob.Status.FAILED
        j1.save(update_fields=["status"])
        j2 = enqueue_assist_job("parse_note", dict(ctx))
        self.assertNotEqual(j1.pk, j2.pk)
        self.assertEqual(
            AssistJob.objects.filter(
                kind=AssistJob.Kind.PARSE_NOTE,
                context__text_hash=j1.context.get("text_hash"),
            ).count(),
            2,
        )

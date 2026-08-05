"""Unit tests for NOTE→ASSIST transport hardening (B1)."""
from django.test import TestCase, override_settings
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from assist.services import (
    handle_agent_event,
    is_agent_transport_error,
    parse_proposal_json,
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

"""Internal routes stay unreachable from the Cloudflare tunnel."""
from __future__ import annotations

import hashlib
import hmac
import json

from django.test import Client, TestCase, override_settings
from django.urls import get_resolver

from api.api import api
from api.auth import BearerAuth
from assist.models import AssistJob, AssistProposal

TOKEN = "internal-token-for-tests-32b"
WEBHOOK = "webhook-secret-for-tests"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Public writes that are not domain mutations. Login is rate-limited.
# Refresh requires a still-valid bearer token in the body or header.
PUBLIC_WRITES = {
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
}


def _sign(payload: dict, secret: str = WEBHOOK) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@override_settings(INTERNAL_API_TOKEN=TOKEN, WEBHOOK_SECRET=WEBHOOK)
class InternalGateTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _assign(self, **extra):
        return self.client.get("/api/internal/intelligence/assign", **extra)

    def test_direct_loopback_with_token_can_read_and_assign(self):
        res = self._assign(HTTP_X_INTERNAL_TOKEN=TOKEN)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("assignments", res.json())

        put = self.client.put(
            "/api/internal/intelligence/assign",
            data=json.dumps({"task": "station_log", "provider": "rules", "section": ""}),
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN=TOKEN,
        )
        self.assertEqual(put.status_code, 200, put.content)
        self.assertEqual(put.json()["provider"], "rules")

    def test_tunnel_headers_rejected_even_with_the_token(self):
        res = self._assign(
            HTTP_X_INTERNAL_TOKEN=TOKEN,
            HTTP_CF_CONNECTING_IP="203.0.113.8",
            HTTP_CF_RAY="abc",
            HTTP_X_FORWARDED_FOR="203.0.113.8",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "forbidden_edge")

    def test_forwarded_for_alone_is_enough_to_reject(self):
        res = self._assign(
            HTTP_X_INTERNAL_TOKEN=TOKEN,
            HTTP_X_FORWARDED_FOR="203.0.113.9",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "forbidden_edge")

    def test_non_loopback_rejected_even_with_the_token(self):
        res = self._assign(
            HTTP_X_INTERNAL_TOKEN=TOKEN,
            REMOTE_ADDR="203.0.113.10",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "forbidden_remote")

    def test_missing_or_wrong_token_is_forbidden(self):
        missing = self._assign()
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.json()["code"], "forbidden")
        wrong = self._assign(HTTP_X_INTERNAL_TOKEN="not-the-token-value!!")
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong.json()["code"], "forbidden")

    @override_settings(INTERNAL_API_TOKEN="")
    def test_unset_token_fails_closed(self):
        res = self._assign(HTTP_X_INTERNAL_TOKEN=TOKEN)
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["code"], "misconfigured")

    @override_settings(INTERNAL_API_TOKEN="too-short")
    def test_short_token_fails_closed(self):
        res = self._assign(HTTP_X_INTERNAL_TOKEN="too-short")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["code"], "misconfigured")

    @override_settings(A2A_INTERNAL_LOOPBACK_ONLY=False)
    def test_loopback_flag_cannot_reopen_the_tunnel(self):
        res = self._assign(
            HTTP_X_INTERNAL_TOKEN=TOKEN,
            HTTP_CF_CONNECTING_IP="203.0.113.8",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "forbidden_edge")

    def _event_payload(self, task_id: str) -> dict:
        return {
            "statusUpdate": {
                "taskId": task_id,
                "contextId": "",
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {
                        "parts": [
                            {
                                "text": (
                                    '{"note":"panko today","target":"line",'
                                    '"target_confidence":"high","components":[]}'
                                )
                            }
                        ]
                    },
                },
            }
        }

    def _post_event(self, payload: dict, *, sig: str | None = None, **extra):
        if sig is None:
            sig = _sign(payload)
        return self.client.post(
            "/api/internal/agent-events",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_A2A_SIGNATURE=sig,
            **extra,
        )

    def test_direct_loopback_hmac_still_accepted(self):
        AssistJob.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "use panko today", "line_id": 1},
            status=AssistJob.Status.RUNNING,
            task_id="task-gate-ok",
        )
        res = self._post_event(self._event_payload("task-gate-ok"))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(
            AssistProposal.objects.filter(task_id="task-gate-ok").count(), 1
        )

    def test_tunnel_cannot_deliver_a_signed_event(self):
        AssistJob.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "use panko today", "line_id": 1},
            status=AssistJob.Status.RUNNING,
            task_id="task-gate-edge",
        )
        res = self._post_event(
            self._event_payload("task-gate-edge"),
            HTTP_CF_CONNECTING_IP="203.0.113.8",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "forbidden_edge")
        self.assertEqual(
            AssistProposal.objects.filter(task_id="task-gate-edge").count(), 0
        )

    def test_bad_signature_still_rejected_on_loopback(self):
        res = self._post_event(self._event_payload("task-gate-bad"), sig="0" * 64)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["code"], "bad_signature")

    @override_settings(WEBHOOK_SECRET="")
    def test_missing_webhook_secret_fails_closed(self):
        res = self._post_event(self._event_payload("task-gate-unset"), sig="abc")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["code"], "misconfigured")


class UnauthenticatedWriteAuditTests(TestCase):
    """Every public write is either login or refresh. Internal routes are not on /api/v1."""

    def test_public_write_surface(self):
        list(api.urls)  # bind routers so auth inheritance is applied
        found: set[tuple[str, str]] = set()
        for bound in api._get_bound_routers():
            for path, path_view in bound.path_operations.items():
                for op in path_view.operations:
                    methods = set(op.methods or [])
                    if not methods & WRITE_METHODS:
                        continue
                    if op.auth_callbacks:
                        self.assertTrue(
                            any(isinstance(cb, BearerAuth) for cb in op.auth_callbacks),
                            f"{methods} {bound.prefix}{path} has a non-bearer auth",
                        )
                        continue
                    for method in sorted(methods & WRITE_METHODS):
                        full = "/" + "/".join(
                            part.strip("/")
                            for part in (bound.prefix, path)
                            if part and part.strip("/")
                        )
                        if not full.startswith("/"):
                            full = "/" + full
                        found.add((method, full))
        self.assertEqual(found, PUBLIC_WRITES)

    def test_internal_routes_are_not_on_v1(self):
        names = []
        for pattern in get_resolver().url_patterns:
            route = str(pattern.pattern)
            names.append(route)
            if "internal" in route:
                self.assertNotIn("api/v1", route)
        self.assertTrue(any("api/internal/agent-events" in r for r in names))
        self.assertTrue(any("api/internal/intelligence/assign" in r for r in names))
        self.assertTrue(any(r.startswith("api/v1/") for r in names))

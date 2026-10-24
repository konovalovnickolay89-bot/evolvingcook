"""Invoice uploads stay raw until an explicit propose."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from api.auth import issue_token
from assist.companion import daily_brief
from assist.models import KitchenInboxItem
from catalog.ingest import (
    IngestError,
    propose_from_upload,
    queue_ingest_extraction,
    run_ingest_extraction,
    store_raw_upload,
)
from catalog.models import CatalogIngestProposal, CatalogIngestUpload

SHEET = '{"items":[{"name":"Olives","base_unit":"ea","confidence":0.95,"supplier_code":"OC174"}]}'


class RawInvoiceUploadTests(TestCase):
    def test_store_does_not_call_the_model_or_create_proposals(self):
        with patch("catalog.ingest.chat_completion_json") as llm:
            upload = store_raw_upload(raw_text="Invoice: milk whole 2L 1.85")
        llm.assert_not_called()
        upload.refresh_from_db()
        self.assertEqual(upload.status, CatalogIngestUpload.Status.PENDING)
        self.assertIsNone(upload.propose_requested_at)
        self.assertEqual(upload.proposals.count(), 0)
        self.assertEqual(CatalogIngestProposal.objects.count(), 0)
        self.assertEqual(KitchenInboxItem.objects.count(), 0)

    def test_empty_text_is_refused(self):
        with self.assertRaises(IngestError):
            store_raw_upload(raw_text="   ")

    def test_queue_and_worker_refuse_without_propose(self):
        upload = store_raw_upload(raw_text="Invoice: butter 250g")
        with patch("django_q.tasks.async_task") as async_task:
            with self.assertRaises(IngestError):
                queue_ingest_extraction(upload.pk)
            async_task.assert_not_called()
        with patch("catalog.ingest.chat_completion_json") as llm:
            result = run_ingest_extraction(upload.pk)
        llm.assert_not_called()
        self.assertEqual(result["skipped"], "propose_not_requested")
        self.assertEqual(upload.proposals.count(), 0)
        self.assertEqual(daily_brief(date(2026, 10, 24))["tips"], [])

    def test_worker_drops_a_queued_upload_that_was_not_asked(self):
        upload = CatalogIngestUpload.objects.create(
            source_kind="text",
            raw_text="Invoice: eggs",
            status=CatalogIngestUpload.Status.QUEUED,
            q_task_id="stale",
        )
        with patch("catalog.ingest.get_api_key", return_value="test-key") as key:
            result = run_ingest_extraction(upload.pk)
        key.assert_not_called()
        self.assertEqual(result["skipped"], "propose_not_requested")
        upload.refresh_from_db()
        self.assertEqual(upload.status, CatalogIngestUpload.Status.PENDING)
        self.assertEqual(upload.q_task_id, "")
        self.assertEqual(upload.proposals.count(), 0)

    def test_explicit_propose_enqueues_and_worker_creates_inbox_not_tips(self):
        upload = store_raw_upload(raw_text="Invoice: olives tin")
        with patch("django_q.tasks.async_task", return_value="q-1") as async_task:
            task_id = propose_from_upload(upload.pk)
        self.assertEqual(task_id, "q-1")
        async_task.assert_called_once()
        self.assertEqual(
            async_task.call_args.args[0], "catalog.ingest.run_ingest_extraction"
        )
        upload.refresh_from_db()
        self.assertIsNotNone(upload.propose_requested_at)
        self.assertEqual(upload.status, CatalogIngestUpload.Status.QUEUED)
        self.assertEqual(upload.proposals.count(), 0)

        with (
            patch("catalog.ingest.get_api_key", return_value="test-key"),
            patch("catalog.ingest._call_llm_strict_json", return_value=SHEET),
        ):
            result = run_ingest_extraction(upload.pk)
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        upload.refresh_from_db()
        self.assertEqual(upload.status, CatalogIngestUpload.Status.REVIEW)
        proposal = upload.proposals.get()
        self.assertEqual(proposal.name, "Olives")
        self.assertEqual(proposal.status, CatalogIngestProposal.Status.PENDING)
        inbox = KitchenInboxItem.objects.get(catalog_proposal=proposal)
        self.assertEqual(inbox.kind, KitchenInboxItem.Kind.CATALOG)
        self.assertEqual(daily_brief(date(2026, 10, 25), refresh=True)["tips"], [])

    def test_upload_api_stores_raw_and_propose_is_separate(self):
        user = get_user_model().objects.create_user(
            "nick", "nick@example.com", "test-pass-123"
        )
        token = issue_token(user)
        client = Client()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        with patch("catalog.ingest.chat_completion_json") as llm:
            created = client.post(
                "/api/v1/assist/invoice-uploads",
                data={"raw_text": "Invoice: milk 2L", "source_kind": "text"},
                content_type="application/json",
                **auth,
            )
        llm.assert_not_called()
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertEqual(body["proposal_count"], 0)
        self.assertFalse(body["propose_requested"])
        self.assertEqual(body["status"], "pending")

        with patch("django_q.tasks.async_task", return_value="q-9"):
            proposed = client.post(
                f"/api/v1/assist/invoice-uploads/{body['id']}/propose",
                **auth,
            )
        self.assertEqual(proposed.status_code, 202, proposed.content)
        self.assertTrue(proposed.json()["queued"])
        self.assertEqual(proposed.json()["task_id"], "q-9")
        upload = CatalogIngestUpload.objects.get(pk=body["id"])
        self.assertIsNotNone(upload.propose_requested_at)
        self.assertGreaterEqual(
            upload.propose_requested_at, timezone.now() - timedelta(minutes=5)
        )
        self.assertEqual(upload.proposals.count(), 0)

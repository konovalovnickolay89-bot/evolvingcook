"""Manual daily brief (no model fill) and kitchen notes."""
import importlib
from datetime import date
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from api.auth import issue_token
from assist import companion
from assist.companion import STANDING_BRIEF_DATE
from assist.kitchen import add_kitchen_note, list_kitchen_notes, resolve_kitchen_note
from assist.models import AssistJob, AssistProposal, CompanionBrief, KitchenInboxItem

manualise_london_brief = importlib.import_module(
    "assist.migrations.0006_manual_brief_kitchen_store"
).manualise_london_brief
from catalog.ingest import store_raw_upload
from catalog.models import CatalogIngestUpload
from planning.models import DishTemplate, ServiceSectionCode

TODAY = date(2026, 10, 24)
NEXT = date(2026, 10, 25)


class ManualBriefTests(TestCase):
    def test_migration_left_london_brief_manual_and_empty(self):
        row = CompanionBrief.objects.get(service_date=TODAY)
        self.assertEqual(row.payload.get("mode"), "manual")
        self.assertEqual(row.payload.get("tips"), [])
        self.assertEqual(row.model, "")

    def test_manualise_wipes_generated_tips_on_that_date(self):
        row = CompanionBrief.objects.get(service_date=TODAY)
        row.payload = {"tips": [{"title": "From the model", "body": "Do this"}]}
        row.model = "mistral-large-latest"
        row.save(update_fields=["payload", "model"])
        manualise_london_brief(apps, None)
        row.refresh_from_db()
        self.assertEqual(row.payload, {"mode": "manual", "tips": []})
        self.assertEqual(row.model, "")

    def test_empty_poll_does_not_call_the_model_or_write(self):
        before = CompanionBrief.objects.count()
        with (
            patch.object(companion, "_call", side_effect=AssertionError("llm")),
            patch.object(
                companion, "build_day_context", side_effect=AssertionError("snapshot")
            ),
        ):
            out = companion.daily_brief(TODAY, refresh=True)
        self.assertEqual(out["mode"], "manual")
        self.assertEqual(out["tips"], [])
        self.assertEqual(out["model"], "")
        self.assertEqual(out["service_date"], TODAY.isoformat())
        self.assertEqual(CompanionBrief.objects.count(), before)

    def test_legacy_model_cache_is_not_returned_or_regenerated(self):
        CompanionBrief.objects.create(
            service_date=date(2026, 10, 22),
            payload={"tips": [{"title": "Generated", "body": "From Mistral"}]},
            model="mistral-large-latest",
        )
        with patch.object(companion, "_call", side_effect=AssertionError("llm")):
            out = companion.daily_brief(date(2026, 10, 22), refresh=True)
        self.assertEqual(out["tips"], [])

    def test_unresolved_tips_carry_across_days_until_resolved(self):
        CompanionBrief.objects.create(
            service_date=date(2026, 10, 20),
            payload={
                "mode": "manual",
                "tips": [
                    {
                        "id": "walkin",
                        "title": "Walk-in",
                        "body": "Check the walk-in seal.",
                        "source": "voice",
                        "created_at": "2026-10-20T08:00:00+01:00",
                        "resolved_at": None,
                    }
                ],
            },
            model="",
        )
        added = companion.add_manual_tip(
            title="Salt", body="Check the salt pig.", source="typed"
        )
        for day in (TODAY, NEXT, date(2026, 12, 1)):
            ids = [t["id"] for t in companion.daily_brief(day, refresh=True)["tips"]]
            self.assertEqual(ids, ["walkin", added["id"]])

        resolved = companion.resolve_manual_tip("walkin")
        self.assertIsNotNone(resolved["resolved_at"])
        for day in (TODAY, NEXT):
            ids = [t["id"] for t in companion.daily_brief(day)["tips"]]
            self.assertEqual(ids, [added["id"]])

    def test_refresh_does_not_overwrite_manual_tips(self):
        tip = companion.add_manual_tip(
            title="Salt", body="Check the salt pig.", source="voice"
        )
        with patch.object(companion, "_call", side_effect=AssertionError("llm")):
            out = companion.daily_brief(TODAY, refresh=True)
        self.assertEqual(out["tips"][0]["body"], "Check the salt pig.")
        self.assertEqual(out["tips"][0]["id"], tip["id"])
        self.assertEqual(out["tips"][0]["source"], "voice")

    def test_edit_delete_and_clear(self):
        first = companion.add_manual_tip(title="Salt", body="Check the salt pig.")
        second = companion.add_manual_tip(
            title="Oil", body="Filter the fryer oil.", source="banto"
        )
        edited = companion.edit_manual_tip(first["id"], body="Top up the salt pig.")
        self.assertEqual(edited["body"], "Top up the salt pig.")
        self.assertEqual(edited["title"], "Salt")
        companion.delete_manual_tip(first["id"])
        with self.assertRaises(companion.CompanionError):
            companion.delete_manual_tip(first["id"])
        cleared = companion.clear_manual_tips()
        self.assertEqual(cleared["tips"], [])
        self.assertEqual(companion.daily_brief(NEXT)["tips"], [])
        standing = CompanionBrief.objects.get(service_date=STANDING_BRIEF_DATE)
        stored = standing.payload["tips"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], second["id"])
        self.assertIsNotNone(stored[0]["resolved_at"])

    def test_set_profile_does_not_drop_tips_or_refill(self):
        companion.add_manual_tip(title="Salt", body="Check the salt pig.")
        companion.set_profile("Fire the jus at 10.")
        with patch.object(companion, "_call", side_effect=AssertionError("llm")):
            out = companion.daily_brief(TODAY, refresh=True)
        self.assertEqual(len(out["tips"]), 1)
        self.assertTrue(
            CompanionBrief.objects.filter(service_date=STANDING_BRIEF_DATE).exists()
        )

    def test_tags_proposals_and_invoices_do_not_become_tips(self):
        DishTemplate.objects.create(
            section=ServiceSectionCode.A_LA_CARTE,
            name="Olives",
            category="snacks",
            notes="NEW · Oct 26 menu · check the tin",
            sort_order=0,
        )
        AssistProposal.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "x" * 20},
            proposal={"note": "order more olives", "target": "line"},
            rationale="Heard on the pass: order more olives",
            status=AssistProposal.Status.PENDING,
        )
        store_raw_upload(raw_text="Invoice: olives tin 2.40")
        self.assertEqual(CatalogIngestUpload.objects.count(), 1)
        self.assertEqual(
            KitchenInboxItem.objects.filter(
                kind=KitchenInboxItem.Kind.ASSIST
            ).count(),
            1,
        )
        with patch.object(companion, "_call", side_effect=AssertionError("llm")):
            out = companion.daily_brief(TODAY, refresh=True)
        self.assertEqual(out["tips"], [])

    def test_bad_source_and_empty_tip(self):
        with self.assertRaises(companion.CompanionError):
            companion.add_manual_tip(title="", body="", source="typed")
        with self.assertRaises(companion.CompanionError):
            companion.add_manual_tip(body="Ok", source="email")


class BriefApiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            "nick", "nick@example.com", "test-pass-123"
        )
        self.token = issue_token(user)
        self.client = Client()

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_write_carry_and_clear_over_http(self):
        created = self.client.post(
            "/api/v1/assist/daily-brief/tips",
            data={"title": "Salt", "body": "Check the salt pig.", "source": "voice"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(created.status_code, 201, created.content)
        tip_id = created.json()["id"]

        for day in (TODAY.isoformat(), NEXT.isoformat()):
            res = self.client.get(
                f"/api/v1/assist/daily-brief?service_date={day}&refresh=true",
                **self._auth(),
            )
            self.assertEqual(res.status_code, 200, res.content)
            body = res.json()
            self.assertEqual(body["mode"], "manual")
            self.assertEqual(body["model"], "")
            self.assertEqual(len(body["tips"]), 1)
            self.assertEqual(body["tips"][0]["id"], tip_id)
            self.assertIsNone(body["tips"][0]["resolved_at"])

        edited = self.client.patch(
            f"/api/v1/assist/daily-brief/tips/{tip_id}",
            data={"body": "Top up the salt pig."},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(edited.status_code, 200, edited.content)
        self.assertEqual(edited.json()["body"], "Top up the salt pig.")

        cleared = self.client.post(
            "/api/v1/assist/daily-brief/clear",
            **self._auth(),
        )
        self.assertEqual(cleared.status_code, 200, cleared.content)
        self.assertEqual(cleared.json()["tips"], [])

    def test_unsigned_brief_is_rejected(self):
        res = self.client.get("/api/v1/assist/daily-brief")
        self.assertEqual(res.status_code, 401)


class KitchenNoteTests(TestCase):
    def test_create_list_and_resolve(self):
        note = add_kitchen_note(
            title="Shallots",
            body="Dictated: brunoise the shallots.",
            source="banto",
        )
        self.assertEqual(note["source"], "banto")
        listed = list_kitchen_notes()
        self.assertEqual([n["id"] for n in listed], [note["id"]])
        resolve_kitchen_note(note["id"])
        self.assertEqual(list_kitchen_notes(), [])
        self.assertEqual(len(list_kitchen_notes(include_resolved=True)), 1)

    def test_note_api_and_empty_body(self):
        user = get_user_model().objects.create_user(
            "nick", "nick@example.com", "test-pass-123"
        )
        token = issue_token(user)
        client = Client()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        bad = client.post(
            "/api/v1/assist/kitchen-notes",
            data={"body": "  ", "source": "voice"},
            content_type="application/json",
            **auth,
        )
        self.assertEqual(bad.status_code, 400, bad.content)
        created = client.post(
            "/api/v1/assist/kitchen-notes",
            data={
                "title": "Pass",
                "body": "Table 12 allergy query — ask the guest.",
                "source": "voice",
            },
            content_type="application/json",
            **auth,
        )
        self.assertEqual(created.status_code, 201, created.content)
        note_id = created.json()["id"]
        listed = client.get("/api/v1/assist/kitchen-notes", **auth)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        resolved = client.post(
            f"/api/v1/assist/kitchen-notes/{note_id}/resolve",
            **auth,
        )
        self.assertEqual(resolved.status_code, 200, resolved.content)
        self.assertIsNotNone(resolved.json()["resolved_at"])
        again = client.get("/api/v1/assist/kitchen-notes", **auth)
        self.assertEqual(again.json(), [])

    def test_assist_proposal_is_inbox_not_a_tip(self):
        proposal = AssistProposal.objects.create(
            kind=AssistJob.Kind.PARSE_NOTE,
            context={"text": "y" * 20},
            proposal={"note": "defrost the brioche"},
            rationale="Defrost the brioche",
            status=AssistProposal.Status.PENDING,
        )
        items = list(KitchenInboxItem.objects.filter(assist_proposal=proposal))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, KitchenInboxItem.Kind.ASSIST)
        proposal.rationale = "edited"
        proposal.save(update_fields=["rationale", "updated_at"])
        self.assertEqual(
            KitchenInboxItem.objects.filter(assist_proposal=proposal).count(), 1
        )
        self.assertEqual(companion.daily_brief(TODAY)["tips"], [])

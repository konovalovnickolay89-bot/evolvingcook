"""D15 section modes unit tests."""
from django.test import TestCase

from assist.models import AssistJob
from assist.services import AssistError, enqueue_assist_job
from planning.models import SectionSetting, ServiceSectionCode
from planning.section_modes import (
    SectionModeError,
    assert_job_allowed,
    board_mode_fields,
    ensure_all_section_settings,
    list_section_settings,
    recommend_mode,
    upsert_section_mode,
)


class SectionSettingsTests(TestCase):
    def test_ensure_six_null_mode(self):
        rows = ensure_all_section_settings()
        self.assertEqual(len(rows), 6)
        for r in rows:
            self.assertIsNone(r.mode)
        banq = SectionSetting.objects.get(section=ServiceSectionCode.BANQUETING)
        self.assertTrue(banq.guided)
        sky = SectionSetting.objects.get(section=ServiceSectionCode.SKYBAR)
        self.assertFalse(sky.guided)

    def test_recommendations(self):
        self.assertEqual(recommend_mode("skybar"), "ordering")
        self.assertEqual(recommend_mode("a_la_carte"), "ordering")
        self.assertEqual(recommend_mode("canteen"), "counts")
        self.assertEqual(recommend_mode("banqueting"), "counts")

    def test_upsert_mode(self):
        obj = upsert_section_mode("skybar", mode="ordering")
        self.assertEqual(obj.mode, "ordering")
        self.assertIsNotNone(obj.decided_at)
        v = board_mode_fields("skybar")
        self.assertEqual(v["section_mode"], "ordering")
        self.assertFalse(v["mode_prompt_needed"])
        self.assertEqual(v["mode_recommendation"], "ordering")

    def test_list_settings(self):
        data = list_section_settings()
        self.assertEqual(len(data), 6)
        self.assertTrue(all("mode_recommendation" in d for d in data))


class ModeGateTests(TestCase):
    def setUp(self):
        ensure_all_section_settings()

    def test_qty_draft_blocked_when_unset(self):
        with self.assertRaises(SectionModeError) as cm:
            assert_job_allowed(kind="qty_draft", section="skybar")
        self.assertEqual(cm.exception.code, "mode_gate")

    def test_qty_draft_blocked_in_ordering(self):
        upsert_section_mode("skybar", mode="ordering")
        with self.assertRaises(SectionModeError):
            assert_job_allowed(kind="qty_draft", section="skybar")

    def test_order_suggest_ok_in_ordering(self):
        upsert_section_mode("skybar", mode="ordering")
        assert_job_allowed(kind="order_suggest", section="skybar")

    def test_prep_plan_requires_guided_counts(self):
        upsert_section_mode("skybar", mode="counts", guided=False)
        with self.assertRaises(SectionModeError):
            assert_job_allowed(kind="prep_plan", section="skybar")
        upsert_section_mode("banqueting", mode="counts", guided=True)
        assert_job_allowed(kind="prep_plan", section="banqueting")

    def test_enqueue_mode_gate(self):
        upsert_section_mode("a_la_carte", mode="ordering")
        with self.assertRaises(AssistError) as cm:
            enqueue_assist_job(
                "qty_draft",
                {"section": "a_la_carte", "service_date": "2026-08-05"},
            )
        self.assertEqual(cm.exception.code, "mode_gate")

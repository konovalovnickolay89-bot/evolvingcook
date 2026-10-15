"""Companion replies render as readable text, never Python reprs (D16)."""
import json
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from assist import companion
from assist.companion import _as_text, _repair_reply

# Shape seen live: JSON mode nested the answer, str() leaked a repr.
NESTED = {
    "actions": [
        "Mise: 250 g clarified butter, 4 egg yolks, 10 g tarragon.",
        "Lead: 09:00 reduce vinegar/wine/shallot (5 min, 1/3 volume).",
        "HACCP: hold at 63 °C, max 2 h — discard if <63 °C.",
    ],
    "tip": "Clarify the butter — milk solids burn and water splits the sauce.",
}
LEGACY_REPR = str(NESTED)  # "{'actions': ['Mise: ...'], 'tip': '...'}"


class AsTextTests(SimpleTestCase):
    def test_string_passes_through(self):
        self.assertEqual(_as_text("  Start the jus.  "), "Start the jus.")

    def test_nested_object_becomes_sections_and_bullets(self):
        text = _as_text(NESTED)
        self.assertNotIn("{'", text)
        self.assertNotIn("['", text)
        self.assertIn("**Actions**\n- Mise: 250 g clarified butter", text)
        self.assertIn("- HACCP: hold at 63 °C", text)
        self.assertIn("**Tip:** Clarify the butter", text)

    def test_single_reply_key_unwraps(self):
        self.assertEqual(_as_text({"reply": "Fire table 4."}), "Fire table 4.")

    def test_list_of_flat_objects_is_one_bullet_each(self):
        text = _as_text([{"time": "06:00", "task": "Blanch asparagus"}])
        self.assertEqual(text, "- Time: 06:00 · Task: Blanch asparagus")

    def test_multiline_item_stays_in_its_bullet(self):
        self.assertEqual(_as_text(["Lead: reduce\nthen strain"]), "- Lead: reduce\n  then strain")

    def test_acronym_keys_keep_their_case(self):
        self.assertEqual(_as_text({"HACCP": "75 °C core"}), "**HACCP:** 75 °C core")
        self.assertEqual(_as_text({"mise_en_place": "x"}), "**Mise en place:** x")

    def test_none_and_numbers(self):
        self.assertEqual(_as_text(None), "")
        self.assertEqual(_as_text(4), "4")


class RepairReplyTests(SimpleTestCase):
    def test_legacy_python_repr_is_repaired(self):
        fixed = _repair_reply(LEGACY_REPR)
        self.assertTrue(fixed.startswith("**Actions**"))
        self.assertNotIn("'actions'", fixed)

    def test_json_string_is_repaired(self):
        self.assertIn("**Tip:**", _repair_reply(json.dumps(NESTED)))

    def test_plain_text_and_garbage_untouched(self):
        self.assertEqual(_repair_reply("Start the jus."), "Start the jus.")
        self.assertEqual(_repair_reply("{not python"), "{not python")


@patch.object(companion, "_require_key", lambda: None)
@patch.object(companion, "build_day_context", lambda d: {"sections": []})
@patch.object(companion, "get_profile", lambda: {"text": "", "updated_at": None})
class CompanionChatShapeTests(SimpleTestCase):
    def _chat(self, model_obj, history=None):
        seen = {}

        def fake_call(system, user_text):
            seen["payload"] = json.loads(user_text)
            return model_obj, "mistral-large-latest"

        msgs = (history or []) + [{"role": "user", "content": "Bernaise sauce"}]
        with patch.object(companion, "_call", fake_call):
            out = companion.companion_chat(msgs, date(2026, 10, 14))
        return out, seen["payload"]

    def test_nested_reply_rendered_as_text(self):
        out, _ = self._chat({"reply": NESTED})
        self.assertTrue(out["reply"].startswith("**Actions**"))
        self.assertNotIn("{'", out["reply"])

    def test_missing_wrapper_rendered_as_text(self):
        out, _ = self._chat(NESTED)
        self.assertIn("**Tip:** Clarify", out["reply"])

    def test_plain_reply_unchanged(self):
        out, _ = self._chat({"reply": "Reduce first, then the yolks."})
        self.assertEqual(out["reply"], "Reduce first, then the yolks.")

    def test_history_reprs_cleaned_and_format_sent(self):
        _, payload = self._chat(
            {"reply": "ok"},
            history=[
                {"role": "user", "content": "Soup of asparagus"},
                {"role": "assistant", "content": LEGACY_REPR},
            ],
        )
        sent = payload["conversation"][1]["content"]
        self.assertTrue(sent.startswith("**Actions**"))
        self.assertIn("phone screen", payload["format"])


@patch.object(companion, "_require_key", lambda: None)
class CompanionInvalidJsonRetryTests(SimpleTestCase):
    def _call_with(self, raws):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return raws[len(calls) - 1]

        with patch.object(companion.llm_provider, "chat_completion_json", fake):
            return companion._call("sys", "user"), len(calls)

    def test_one_retry_after_invalid_json(self):
        broken = '{"reply": "Hot dip is "off" the menu."}'  # shape seen live
        (data, _), n = self._call_with([broken, '{"reply": "Hot dip is off."}'])
        self.assertEqual(data, {"reply": "Hot dip is off."})
        self.assertEqual(n, 2)

    def test_valid_json_is_not_retried(self):
        (data, _), n = self._call_with(['{"reply": "ok"}'])
        self.assertEqual((data, n), ({"reply": "ok"}, 1))

    def test_gives_up_after_the_retry(self):
        with self.assertRaises(companion.CompanionError) as cm:
            self._call_with(['{"reply": "x', "[1]"])
        self.assertIn("invalid JSON", str(cm.exception))

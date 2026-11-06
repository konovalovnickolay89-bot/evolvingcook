"""Companion refuses allergen-absence claims and only emits UK 14 names."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from assist import companion
from assist.allergen_safety import (
    ALLERGEN_DEFERENCE,
    ALLERGEN_SAFETY_REFUSAL,
    BANNED_ALLERGEN_CLAIMS,
    guard_allergen_claims,
)
from catalog.allergens import UK14_ALLERGENS


class GuardTests(SimpleTestCase):
    def test_each_banned_claim_is_removed_and_the_rest_kept(self):
        for phrase in BANNED_ALLERGEN_CLAIMS:
            reply = guard_allergen_claims(
                f"Reduce the stock. This dish is {phrase}. Hold at 75 C."
            )
            self.assertNotIn(phrase, reply.lower())
            self.assertIn("Reduce the stock.", reply)
            self.assertIn("Hold at 75 C.", reply)
            self.assertIn(ALLERGEN_DEFERENCE, reply)
            self.assertIn("allergens not recorded", reply)

    def test_clean_text_is_unchanged(self):
        text = "Reduce first, then the yolks."
        self.assertIs(guard_allergen_claims(text), text)

    def test_claim_only_reply_is_the_deference(self):
        phrase = BANNED_ALLERGEN_CLAIMS[0]
        self.assertEqual(guard_allergen_claims(f"This dish is {phrase}."), ALLERGEN_DEFERENCE)


class CompanionAllergenTests(SimpleTestCase):
    def test_system_prompt_carries_the_refusal(self):
        self.assertIn(ALLERGEN_SAFETY_REFUSAL, companion.SYSTEM_PROMPT)
        for phrase in BANNED_ALLERGEN_CLAIMS:
            self.assertIn(phrase, companion.SYSTEM_PROMPT.lower())
        self.assertIn("allergens not recorded", companion.SYSTEM_PROMPT)
        self.assertIn("allergen matrix", companion.SYSTEM_PROMPT.lower())

    def test_recipe_task_names_the_allowlist_and_does_not_claim_absence(self):
        for name in UK14_ALLERGENS:
            self.assertIn(name, companion.RECIPE_TASK)
        self.assertIn("allergens not recorded", companion.RECIPE_TASK)
        for phrase in BANNED_ALLERGEN_CLAIMS:
            self.assertNotIn(phrase, companion.RECIPE_TASK.lower())

    @patch.object(companion, "_require_key", lambda: None)
    @patch.object(companion, "build_day_context", lambda d: {"sections": []})
    @patch.object(companion, "build_house_stock_context", lambda: {})
    @patch.object(companion, "get_profile", lambda: {"text": "", "updated_at": None})
    def test_chat_output_defers_instead_of_clearing_an_allergen(self):
        phrase = BANNED_ALLERGEN_CLAIMS[3]

        def fake_call(system, user_text):
            self.assertIn(ALLERGEN_SAFETY_REFUSAL, system)
            return {"reply": f"The gravy is {phrase} coeliacs. Reduce first."}, "m"

        with patch.object(companion, "_call", fake_call):
            out = companion.companion_chat(
                [{"role": "user", "content": "Any issue with the gravy?"}],
                date(2026, 10, 15),
            )
        self.assertNotIn(phrase, out["reply"].lower())
        self.assertIn("Reduce first.", out["reply"])
        self.assertIn("allergens not recorded", out["reply"])

    @patch.object(companion, "_require_key", lambda: None)
    @patch.object(companion, "get_profile", lambda: {"text": "", "updated_at": None})
    def test_draft_filters_names_and_strips_claims(self):
        claim = BANNED_ALLERGEN_CLAIMS[0]
        absence = BANNED_ALLERGEN_CLAIMS[2]

        def fake_call(system, user_text):
            payload = json.loads(user_text)
            self.assertIn("cereals containing gluten", payload["task"])
            return {
                "name": f"{claim} gravy",
                "ingredients": [{"name": "flour", "qty": 100, "unit": "g", "note": ""}],
                "method": ["Sweat the onion.", f"The sauce is {absence} gluten."],
                "allergens": ["gluten", "sparkles", "peanuts", "soy"],
                "notes": f"It is {claim}.",
            }, "mistral-large-latest"

        with patch.object(companion, "_call", fake_call):
            card = companion.draft_recipe("gravy for four", 4)
        self.assertEqual(card["name"], "gravy for four")
        self.assertEqual(
            card["allergens"],
            ["cereals containing gluten", "peanuts", "soya"],
        )
        self.assertIn("Sweat the onion.", card["method"][0])
        self.assertNotIn(absence, " ".join(card["method"]).lower())
        self.assertNotIn(claim, card["notes"].lower())
        self.assertIn("allergens not recorded", card["notes"])

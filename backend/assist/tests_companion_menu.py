"""Companion snapshot carries the live menu from dish templates (D16)."""
import json
from datetime import date
from unittest.mock import patch

from django.test import TestCase

from assist import companion
from catalog.models import Item
from planning.models import DishTemplate, DishTemplateComponent, ServiceSectionCode

ALC = ServiceSectionCode.A_LA_CARTE


class CompanionMenuContextTests(TestCase):
    def setUp(self):
        burger = DishTemplate.objects.create(
            section=ALC,
            name="Korean Chicken Burger",
            category="burgers",
            notes="CHANGED · Oct 26 menu · £20 · with skinny fries",
            sort_order=10,
        )
        thigh = Item.objects.create(name="Chicken thigh")
        DishTemplateComponent.objects.create(template=burger, item=thigh, sort_order=0)
        DishTemplateComponent.objects.create(template=burger, item=thigh, sort_order=5)
        DishTemplateComponent.objects.create(template=burger, name="Asian slaw", sort_order=10)
        DishTemplate.objects.create(
            section=ALC,
            name="Olives",
            category="snacks",
            notes="NEW · Oct 26 menu",
            sort_order=0,
        )
        DishTemplate.objects.create(
            section=ALC, name="KIDS MAC AND CHEESE", category=ALC, sort_order=1000
        )
        DishTemplate.objects.create(
            section=ALC, name="PLANET BURGER", category="burgers", active=False
        )

    def test_menu_lists_active_dishes_with_notes_and_components(self):
        ctx = companion.build_day_context(date(2026, 10, 15))
        alc = ctx["menu"][ALC]
        self.assertEqual(alc["snacks"], ["Olives"])
        self.assertEqual(
            alc["burgers"],
            ["Korean Chicken Burger — £20 · with skinny fries | Chicken thigh; Asian slaw"],
        )
        self.assertEqual(alc["other"], ["KIDS MAC AND CHEESE"])
        self.assertEqual(ctx["off_menu"], {ALC: ["PLANET BURGER"]})

    def test_new_and_changed_tags_become_an_explicit_list(self):
        ctx = companion.build_day_context(date(2026, 10, 15))
        self.assertEqual(
            ctx["menu_changes"],
            {ALC: {"new": ["Olives"], "changed": ["Korean Chicken Burger"]}},
        )
        self.assertNotIn("Oct 26", json.dumps(ctx["menu"], ensure_ascii=False))

    def test_menu_ships_even_when_the_day_is_not_open(self):
        ctx = companion.build_day_context(date(2026, 10, 16))
        self.assertEqual(ctx["day_status"], "not_open")
        self.assertIn("burgers", ctx["menu"][ALC])

    def test_long_notes_and_component_lists_are_capped(self):
        t = DishTemplate.objects.get(name="Olives")
        t.notes = "x" * 500
        t.save()
        for i in range(companion.MAX_MENU_COMPONENTS + 3):
            DishTemplateComponent.objects.create(template=t, name=f"c{i}", sort_order=i)
        line = companion.build_day_context(date(2026, 10, 15))["menu"][ALC]["snacks"][0]
        note = line.split(" — ", 1)[1].split(" | ", 1)[0]
        self.assertEqual(len(note), companion.MAX_MENU_NOTE_CHARS)
        self.assertTrue(line.endswith("c19 (+3 more)"))

    @patch.object(companion, "_require_key", lambda: None)
    @patch.object(companion, "get_profile", lambda: {"text": "", "updated_at": None})
    def test_chat_prompt_carries_the_menu(self):
        seen = {}

        def fake_call(system, user_text):
            seen["system"], seen["payload"] = system, json.loads(user_text)
            return {"reply": "ok"}, "mistral-large-latest"

        with patch.object(companion, "_call", fake_call):
            companion.companion_chat(
                [{"role": "user", "content": "What's new on the menu?"}],
                date(2026, 10, 15),
            )
        snap = seen["payload"]["day_snapshot"]
        self.assertIn("Olives", snap["menu"][ALC]["snacks"])
        self.assertIn("off_menu", seen["system"])

"""UK 14 allowlist: aliases map, unknown names are rejected, migration is safe."""
import importlib

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from api.auth import issue_token
from catalog.allergens import UK14_ALLERGENS, UnknownAllergen, normalize_allergens
from catalog.models import Item, Recipe

forwards = importlib.import_module(
    "catalog.migrations.0005_uk14_allergen_names"
).forwards


class NormalizeAllergenTests(TestCase):
    def test_canonical_order_and_aliases(self):
        self.assertEqual(
            normalize_allergens(
                ["nuts", "Gluten", "soya", "peanuts", "shellfish", "nuts"],
                strict=True,
            ),
            [
                "cereals containing gluten",
                "crustaceans",
                "molluscs",
                "tree nuts",
                "peanuts",
                "soya",
            ],
        )

    def test_unknown_is_rejected_when_strict_and_dropped_otherwise(self):
        with self.assertRaises(UnknownAllergen) as caught:
            normalize_allergens(["milk", "garlic"], strict=True)
        self.assertEqual(caught.exception.unknown, ["garlic"])
        self.assertEqual(
            normalize_allergens(["milk", "garlic", ""], strict=False),
            ["milk"],
        )

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_allergens(None), [])
        self.assertEqual(normalize_allergens([]), [])
        self.assertEqual(len(UK14_ALLERGENS), 14)


class AllergenApiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            "chef", "chef@kitchen.test", "correct-horse-battery"
        )
        self.client = Client()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {issue_token(user)}"}

    def test_create_maps_aliases_and_rejects_unknown(self):
        bad = self.client.post(
            "/api/v1/recipes",
            data={"name": "Soup", "allergens": ["garlic"]},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["code"], "unknown_allergen")

        ok = self.client.post(
            "/api/v1/recipes",
            data={
                "name": "Soup",
                "ingredients": [{"name": "flour", "qty": 100, "unit": "g"}],
                "method": ["Sweat the onion."],
                "allergens": ["gluten", "soy"],
            },
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(
            ok.json()["allergens"],
            ["cereals containing gluten", "soya"],
        )
        stored = Recipe.objects.get(name="Soup")
        self.assertEqual(stored.allergens, ["cereals containing gluten", "soya"])

    def test_empty_allergens_round_trip(self):
        res = self.client.post(
            "/api/v1/recipes",
            data={"name": "Stock", "allergens": []},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["allergens"], [])


class AllergenMigrationTests(TestCase):
    def test_forwards_rewrites_legacy_rows_and_is_idempotent(self):
        recipe = Recipe.objects.create(name="Legacy soup", allergens=[])
        item = Item.objects.create(name="Legacy flour", base_unit="g", allergens=[])
        # Bypass Model.save, which already canonicalises, to plant old values.
        Recipe.objects.filter(pk=recipe.pk).update(
            allergens=["gluten", "nuts", "sparkles", "peanuts"]
        )
        Item.objects.filter(pk=item.pk).update(allergens=["soy", "milk", "garlic"])

        forwards(apps, None)
        recipe.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(
            recipe.allergens,
            ["cereals containing gluten", "tree nuts", "peanuts"],
        )
        self.assertEqual(item.allergens, ["milk", "soya"])

        forwards(apps, None)
        recipe.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(
            recipe.allergens,
            ["cereals containing gluten", "tree nuts", "peanuts"],
        )
        self.assertEqual(item.allergens, ["milk", "soya"])

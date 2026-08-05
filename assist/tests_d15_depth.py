"""D15 depth: target accepts + ordering assist."""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from assist.d15_targets import TargetApplyError, apply_d15_target
from assist.models import AssistJob, AssistProposal
from assist.services import accept_assist_proposal, proposal_has_structure
from catalog.models import Item
from planning.models import (
    LineComponent,
    ProductionLine,
    ServiceDay,
    ServiceSection,
    ServiceSectionCode,
)
from planning.ordering_assist import dish_order_summary, ingredient_status_for_item
from planning.section_modes import ensure_all_section_settings, upsert_section_mode


class ProposalStructureD15Tests(TestCase):
    def test_component_fill_needs_components(self):
        self.assertFalse(
            proposal_has_structure({"target": "component_fill", "components": []})
        )
        self.assertTrue(
            proposal_has_structure(
                {
                    "target": "component_fill",
                    "components": [{"name": "panko"}],
                }
            )
        )

    def test_order_packs_needs_lines(self):
        self.assertFalse(proposal_has_structure({"target": "order_packs"}))
        self.assertTrue(
            proposal_has_structure(
                {"target": "order_packs", "lines": [{"item_id": 1, "packs": 1}]}
            )
        )


class PlannedQtyAcceptTests(TestCase):
    def setUp(self):
        ensure_all_section_settings()
        upsert_section_mode("canteen", mode="counts")
        self.day = ServiceDay.objects.create(service_date=timezone.localdate())
        self.sec = ServiceSection.objects.create(
            service_day=self.day, section=ServiceSectionCode.CANTEEN
        )
        self.line = ProductionLine.objects.create(
            service_section=self.sec,
            name="Mac cheese",
            mode=ProductionLine.Mode.PRODUCE,
            kind=ProductionLine.Kind.DISH,
            unit="ea",
        )

    def test_accept_planned_qty(self):
        p = AssistProposal.objects.create(
            kind="qty_draft",
            context={"section": "canteen", "line_id": self.line.pk},
            proposal={
                "target": "planned_qty",
                "line_id": self.line.pk,
                "planned_qty": 42,
            },
            status=AssistProposal.Status.PENDING,
        )
        accept_assist_proposal(p.pk)
        self.line.refresh_from_db()
        self.assertEqual(self.line.planned_qty, Decimal("42"))
        p.refresh_from_db()
        self.assertEqual(p.status, AssistProposal.Status.ACCEPTED)


class ComponentFillAcceptTests(TestCase):
    def setUp(self):
        ensure_all_section_settings()
        upsert_section_mode("skybar", mode="ordering")
        self.day = ServiceDay.objects.create(service_date=timezone.localdate())
        self.sec = ServiceSection.objects.create(
            service_day=self.day, section=ServiceSectionCode.SKYBAR
        )
        self.line = ProductionLine.objects.create(
            service_section=self.sec,
            name="Skybar nachos",
            mode=ProductionLine.Mode.CHECK,
            kind=ProductionLine.Kind.DISH,
        )
        self.item = Item.objects.create(name="Tortilla chip", base_unit="g", active=True)

    def test_fill_components(self):
        p = AssistProposal.objects.create(
            kind="menu_completeness",
            context={"section": "skybar", "line_id": self.line.pk},
            proposal={
                "target": "component_fill",
                "line_id": self.line.pk,
                "components": [
                    {"name": "Tortilla chip", "item_id": self.item.pk, "qty": 500, "unit": "g"}
                ],
            },
            status=AssistProposal.Status.PENDING,
        )
        accept_assist_proposal(p.pk)
        self.assertEqual(LineComponent.objects.filter(line=self.line).count(), 1)
        c = LineComponent.objects.get(line=self.line)
        self.assertEqual(c.item_id, self.item.pk)


class OrderingSummaryTests(TestCase):
    def test_dish_summary(self):
        comps = [
            {"stock_status": "in_stock"},
            {"stock_status": "running_low"},
            {"stock_status": "on_order"},
        ]
        s = dish_order_summary(comps)
        self.assertEqual(s["ingredient_count"], 3)
        self.assertEqual(s["to_order_count"], 1)
        self.assertIn("to order", s["label"])

    def test_unknown_without_item(self):
        st = ingredient_status_for_item(None)
        self.assertEqual(st["status"], "unknown")

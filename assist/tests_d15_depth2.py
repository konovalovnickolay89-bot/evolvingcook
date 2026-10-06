"""D15.1 depth tests — qty draft, prep LLM apply, walk shortfall, par stock."""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from assist.services import handle_agent_event
from catalog.models import Item, ParLevel, StorageArea
from inventory.models import StockBalance
from planning.d15_depth import (
    apply_prep_plan_llm_payload,
    ensure_qty_draft_proposals,
    walk_shortfall_order_lines,
)
from planning.models import ProductionLine, ServiceDay, ServiceSection, ServiceSectionCode
from planning.ordering_assist import ingredient_status_for_item
from planning.section_modes import ensure_all_section_settings, upsert_section_mode
from walks.models import Walk, WalkLine


class QtyDraftTests(TestCase):
    def setUp(self):
        ensure_all_section_settings()
        upsert_section_mode("canteen", mode="counts")
        self.day = ServiceDay.objects.create(service_date=timezone.localdate())
        self.sec = ServiceSection.objects.create(
            service_day=self.day,
            section=ServiceSectionCode.CANTEEN,
            covers=40,
        )
        self.line = ProductionLine.objects.create(
            service_section=self.sec,
            name="Staff stew",
            mode=ProductionLine.Mode.PRODUCE,
            kind=ProductionLine.Kind.DISH,
            proposed_qty=Decimal("25"),
            unit="ea",
        )

    def test_qty_draft_from_proposed(self):
        created = ensure_qty_draft_proposals(
            service_date=self.day.service_date, section="canteen"
        )
        self.assertGreaterEqual(len(created), 1)
        p = created[0]
        self.assertEqual(p.proposal.get("target"), "planned_qty")
        self.assertEqual(p.proposal.get("planned_qty"), 25.0)
        self.assertTrue(p.proposal.get("working"))


class PrepPlanLlmApplyTests(TestCase):
    def setUp(self):
        ensure_all_section_settings()
        upsert_section_mode("banqueting", mode="counts", guided=True)
        self.day = ServiceDay.objects.create(service_date=timezone.localdate())
        self.ctx = {
            "section": "banqueting",
            "service_date": str(self.day.service_date),
            "covers": 100,
        }
        AssistProposal.objects.create(
            kind="prep_plan",
            context=self.ctx,
            proposal={"target": "prep_step", "title": "old", "phase": "mep", "working": "x"},
            status=AssistProposal.Status.PENDING,
        )

    def test_replace_steps(self):
        job = AssistJob.objects.create(
            kind="prep_plan", context=self.ctx, status=AssistJob.Status.RUNNING
        )
        out = apply_prep_plan_llm_payload(
            job=job,
            task_id="task-prep-1",
            payload={
                "steps": [
                    {
                        "title": "Reduce jus",
                        "phase": "mep",
                        "order_index": 0,
                        "working": "overnight reduce 4L → 1L",
                    },
                    {
                        "title": "Plate garnish",
                        "phase": "day_of",
                        "clock_time": "11:30",
                        "order_index": 1,
                        "working": "service 12:30 minus 60m",
                    },
                ]
            },
            context=self.ctx,
        )
        self.assertEqual(out["action"], "prep_plan_replaced")
        self.assertEqual(len(out["proposal_ids"]), 2)
        pending = AssistProposal.objects.filter(
            kind="prep_plan", status=AssistProposal.Status.PENDING
        )
        self.assertEqual(pending.count(), 2)
        job.refresh_from_db()
        self.assertEqual(job.status, AssistJob.Status.SUCCEEDED)


class ParAwareStockTests(TestCase):
    def test_below_par_running_low(self):
        area = StorageArea.objects.create(name="test dry", kind=StorageArea.Kind.DRY)
        item = Item.objects.create(
            name="Rice test", base_unit="g", active=True, default_area=area
        )
        ParLevel.objects.create(item=item, area=area, weekday=None, qty=Decimal("1000"))
        StockBalance.objects.create(item=item, area=area, qty=Decimal("100"))
        st = ingredient_status_for_item(item.pk)
        self.assertEqual(st["status"], "running_low")
        self.assertEqual(st["par_qty"], 1000.0)


class WalkShortfallTests(TestCase):
    def test_shortfall_packs(self):
        area = StorageArea.objects.create(name="walk area", kind=StorageArea.Kind.WALKIN)
        item = Item.objects.create(name="Milk test", base_unit="ml", active=True)
        ParLevel.objects.create(item=item, area=area, weekday=None, qty=Decimal("10"))
        walk = Walk.objects.create(status=Walk.Status.DRAFT, area=area)
        WalkLine.objects.create(
            walk=walk,
            item=item,
            area=area,
            counted_qty=Decimal("2"),
            qty_base=Decimal("2"),
            skipped=False,
        )
        rows = walk_shortfall_order_lines(walk.pk)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["packs"], 1)
        self.assertIn("shortfall", rows[0]["why"])

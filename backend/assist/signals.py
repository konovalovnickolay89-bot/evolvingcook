"""Glue existing proposal queues into the kitchen inbox.

Creating an AssistProposal or CatalogIngestProposal records a pointer.
Nothing here writes a daily-brief tip.
"""
from __future__ import annotations

from django.db.models.signals import post_save


def connect() -> None:
    from assist.models import AssistProposal
    from catalog.models import CatalogIngestProposal

    post_save.connect(
        _assist_proposal_saved,
        sender=AssistProposal,
        dispatch_uid="assist.kitchen.assist_proposal",
    )
    post_save.connect(
        _catalog_proposal_saved,
        sender=CatalogIngestProposal,
        dispatch_uid="assist.kitchen.catalog_proposal",
    )


def _assist_proposal_saved(sender, instance, created, **kwargs):
    if not created:
        return
    from assist.kitchen import attach_assist_proposal

    attach_assist_proposal(instance)


def _catalog_proposal_saved(sender, instance, created, **kwargs):
    if not created:
        return
    from assist.kitchen import attach_catalog_proposal

    attach_catalog_proposal(instance)

"""Pagination/cursor discipline shared by the provider adapters (slice 5).

One owner for three rules:

- A page's checkpoint becomes stageable ONLY after the page's records have
  fully committed. `PageDrain.consume` runs the caller's commit callback
  first; if it raises (a fault mid-page), the checkpoint does not move, and
  replaying the page converges on the coordinator's replay dedup.
- The active cursor never regresses: a late-arriving page whose
  `completed_until` precedes the staged value still commits its records as
  evidence, but cannot move the boundary backwards.
- A checkpoint is never torn: only a strictly advancing timed page replaces a
  timed checkpoint. An untimed page (or an equal/older window) may commit its
  records but never rewrites the checkpoint_ref of a timed checkpoint.

Staged checkpoints are handed to `publish_release`, which activates them only
after the release is published (I2). Provider failures produce a failed
capture as evidence and advance nothing.
"""
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator, FormatChecker

from news_lake.adapters.urls import redact_userinfo
from news_lake.context import parse_instant
from news_lake.contract.records import SCHEMA

# A checkpoint is a release sub-object, not a record: validate the fragment
# against its own definition (the release's corpus check re-validates it later).
_CHECKPOINT_VALIDATOR = Draft202012Validator(
    {**SCHEMA['$defs']['checkpoint'], '$defs': SCHEMA['$defs']},
    format_checker=FormatChecker(),
)


@dataclass
class Page:
    """One fully-parsed provider page: records plus its checkpoint claim.

    checkpoint_ref None means the page produced no advancement (failed or
    not-modified fetch); its records (e.g. a failed capture) still commit.
    """

    records: list = field(default_factory=list)
    checkpoint_ref: str = None
    completed_until: str = None


class PageDrain:
    def __init__(self, connector_key, commit, active_checkpoint=None):
        self.connector_key = connector_key
        self.commit = commit
        self._checkpoint_ref = None
        self._completed_until = None
        if active_checkpoint is not None:
            # Optional cross-cycle seed: a drain starts at the control store's
            # active cursor so the first older page cannot regress it.
            self._completed_until = active_checkpoint.get('completed_until')
            ref = active_checkpoint.get('checkpoint_ref')
            if ref is not None:
                self._checkpoint_ref = redact_userinfo(ref)

    def consume(self, page):
        """Commit the page, then (only then) make its checkpoint stageable."""
        self.commit(page.records)
        if page.checkpoint_ref is not None:
            self._advance(page.checkpoint_ref, page.completed_until)

    def checkpoint(self):
        """The stageable checkpoint (seeded from active_checkpoint when supplied),
        or None when no checkpoint has been recorded."""
        if self._checkpoint_ref is None:
            return None
        record = {'connector_key': self.connector_key, 'checkpoint_ref': self._checkpoint_ref}
        if self._completed_until is not None:
            record['completed_until'] = self._completed_until
        _CHECKPOINT_VALIDATOR.validate(record)
        return record

    def _advance(self, ref, until):
        # The active cursor never regresses. A timed checkpoint is only
        # replaced by a strictly later timed page; an untimed page or an
        # equal/older window commits its records but leaves both the boundary
        # and its ref untouched (no torn hybrid checkpoint).
        if self._completed_until is not None:
            if until is None:
                return
            if parse_instant(until) <= parse_instant(self._completed_until):
                return
        self._completed_until = until
        self._checkpoint_ref = redact_userinfo(ref)

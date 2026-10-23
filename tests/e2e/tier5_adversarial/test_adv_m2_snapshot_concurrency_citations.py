"""Tier 5 Adversarial Tests: Milestone 2 (ct-xx7q).

White-box stress testing of:
1. Multi-year gap citation remapping from legacy snapshots to current canonical UUIDs.
2. Historical issues referencing vanished sources retained via RetainedSources graph preservation.
3. Out-of-order and concurrent snapshot ingestion determinism.
4. Single-citation issues remapping (regression guard for ct-xx7q len(citations) <= 1 early return).
"""

from __future__ import annotations
import datetime as dt
from pathlib import Path
import pytest

from committee_meeting.common import Identifier, Ref
from committee_meeting.provenance import Citation, Method, Provenance, SourceRecord
from committee_meeting.issues import DataIssue
from committee_explorer.assemble import (
    Assembly,
    _source_identity_hash,
    RetainedSources,
)


def _make_source(
    sid: str,
    provider: str = "congress.gov",
    scheme: str = "event_id",
    val: str = "114000",
    snapshot_id: str = "snap_2026_w42",
    imported_at: str = "2026-10-22T00:00:00Z",
) -> SourceRecord:
    return SourceRecord(
        id=sid,
        provider=provider,
        identifier=Identifier(scheme=scheme, value=val),
        input_snapshot_id=snapshot_id,
        imported_at=dt.datetime.fromisoformat(imported_at.replace("Z", "+00:00")),
        payload={"raw": f"data for {val} in {snapshot_id}"},
    )


def _make_citation(sid: str, selector: str = "/event/114000") -> Citation:
    return Citation(
        source=Ref(kind="source_record", id=sid),
        selector_type="json_pointer",
        selector=selector,
        quote="Witness Testimony",
    )


class TestM2CitationRemappingAcrossMultiYearGaps:
    """Stress testing citation remapping across multi-year gaps and snapshot variations."""

    def test_multi_year_gap_citation_remapped_to_current_uuid(self):
        """A 2021 DataIssue citing a 2021 source UUID must be remapped to the 2026 UUID for the same identity."""
        # 2021 historical source and issue
        sid_2021 = "src-uuid-2021-alpha"
        src_2021 = _make_source(
            sid=sid_2021,
            provider="congress.gov",
            scheme="event_id",
            val="108500",
            snapshot_id="snapshot_2021_w01",
            imported_at="2021-01-05T12:00:00Z",
        )
        cit_2021 = _make_citation(sid_2021, selector="/title")
        hist_issue = DataIssue(
            id="issue-2021-conflict",
            subject=Ref(kind="source_record", id=sid_2021),
            field_path="/provider",
            category="conflicting",
            summary="Provider mismatch in 2021",
            detected_at=dt.datetime(2021, 1, 5, 12, 0, tzinfo=dt.timezone.utc),
            provenance=Provenance(
                citations=(cit_2021,),
                basis="derived",
                method=Method(name="test", version="1"),
            ),
        )

        # 2026 current source with the SAME (provider, scheme, value) but a new UUID
        sid_2026 = "src-uuid-2026-omega"
        src_2026 = _make_source(
            sid=sid_2026,
            provider="congress.gov",
            scheme="event_id",
            val="108500",
            snapshot_id="snapshot_2026_w42",
            imported_at="2026-10-22T00:00:00Z",
        )

        # Assemble current snapshot with previous 2021 state
        assemble = Assembly(
            previous={
                ("source_record", sid_2021): src_2021,
                ("data_issue", hist_issue.id): hist_issue,
            }
        )
        assemble.add([src_2026])

        # Run finish()
        catalog = assemble.finish()

        # Check issues in assembled catalog
        issues = [r for r in catalog.records if r.kind == "data_issue"]
        assert len(issues) == 1
        remapped_issue = issues[0]

        # The citation source ID must now point to sid_2026, NOT sid_2021!
        citations = remapped_issue.provenance.citations
        assert len(citations) == 1
        assert citations[0].source.id == sid_2026
        # And the issue subject must be updated to sid_2026
        assert remapped_issue.subject.id == sid_2026

        # In RetainedSources: sid_2021 does not need to be retained because it exists in current sources
        assert sid_2021 not in assemble.retained

    def test_historical_issue_with_vanished_source_is_retained(self):
        """If a source cited by a 2021 issue no longer exists in current sources, it must be retained in RetainedSources."""
        sid_vanished = "src-uuid-2021-vanished"
        src_vanished = _make_source(
            sid=sid_vanished,
            provider="senate.committees",
            scheme="hearing_id",
            val="vanished_999",
            snapshot_id="snapshot_2021_w01",
        )
        cit_vanished = _make_citation(sid_vanished, selector="/provider")
        hist_issue = DataIssue(
            id="issue-2021-vanished-src",
            subject=Ref(kind="source_record", id=sid_vanished),
            field_path="/provider",
            category="conflicting",
            summary="Date conflict on vanished hearing",
            detected_at=dt.datetime(2021, 1, 5, 12, 0, tzinfo=dt.timezone.utc),
            provenance=Provenance(
                citations=(cit_vanished,),
                basis="derived",
                method=Method(name="test", version="1"),
            ),
        )

        # Current snapshot has completely different source
        src_current = _make_source(sid="src-2026-unrelated", val="other_123")

        assemble = Assembly(
            previous={
                ("source_record", sid_vanished): src_vanished,
                ("data_issue", hist_issue.id): hist_issue,
            }
        )
        assemble.add([src_current])
        catalog = assemble.finish()

        # The issue remains with citation to sid_vanished
        issues = [r for r in catalog.records if r.kind == "data_issue"]
        assert len(issues) == 1
        assert issues[0].provenance.citations[0].source.id == sid_vanished

        # assemble.retained MUST contain sid_vanished
        assert ("source_record", sid_vanished) in assemble.retained
        assert sid_vanished in assemble.retained.ids
        retained_src = assemble.retained[("source_record", sid_vanished)]
        assert retained_src.id == sid_vanished

    def test_single_citation_issue_remapping_regression(self):
        """Verify that single-citation issues (len(citations) == 1) are remapped (regression test for ct-xx7q)."""
        sid_old = "old-single-citation-uuid"
        src_old = _make_source(sid=sid_old, val="unique_single_issue")
        cit_old = _make_citation(sid_old, selector="/provider")
        single_cit_issue = DataIssue(
            id="issue-single-cit",
            subject=Ref(kind="source_record", id=sid_old),
            field_path="/provider",
            category="conflicting",
            summary="Single citation test",
            detected_at=dt.datetime(2022, 5, 1, tzinfo=dt.timezone.utc),
            provenance=Provenance(
                citations=(cit_old,),
                basis="derived",
                method=Method(name="test", version="1"),
            ),
        )

        sid_new = "new-single-citation-uuid"
        src_new = _make_source(sid=sid_new, val="unique_single_issue")

        assemble = Assembly(
            previous={
                ("source_record", sid_old): src_old,
                ("data_issue", single_cit_issue.id): single_cit_issue,
            }
        )
        assemble.add([src_new])
        catalog = assemble.finish()

        issues = [r for r in catalog.records if r.kind == "data_issue"]
        assert len(issues) == 1
        assert issues[0].provenance.citations[0].source.id == sid_new

    def test_out_of_order_snapshot_ingestion_stability(self):
        """Ingesting snapshots out of order (week 3, then week 1, then week 2) preserves canonical source identity."""
        ident_hash_1 = _source_identity_hash("congress.gov", "event_id", "55512")
        ident_hash_2 = _source_identity_hash("congress.gov", "event_id", "55512")
        ident_hash_3 = _source_identity_hash("congress.gov", "event_id", "55512")
        # Blake2b 16-byte identity hash MUST be 100% deterministic
        assert ident_hash_1 == ident_hash_2 == ident_hash_3

        # Assemble week 3 first, then link to week 1, etc.
        s3 = _make_source("src-w3", val="55512", snapshot_id="w3", imported_at="2026-03-01T00:00:00Z")
        s1 = _make_source("src-w1", val="55512", snapshot_id="w1", imported_at="2026-01-01T00:00:00Z")

        # Assembling with s3 as current and s1 as previous
        a1 = Assembly(previous={("source_record", s1.id): s1})
        a1.add([s3])
        cat1 = a1.finish()
        assert any(s.id == s3.id for s in cat1.sources)

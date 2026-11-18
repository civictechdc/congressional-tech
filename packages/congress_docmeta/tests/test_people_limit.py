"""The people limit (`schema_v4.MAX_PERSONAS`) and the roster guard that stopped depending on it (ct-bult)."""

from __future__ import annotations

from typing import Any

from congress_docmeta.anomaly_router_v6 import (
    ROSTER_LEAK_MEMBER_LIMIT_V6,
    roster_shaped_members_v6,
    score_docmeta_anomalies_v6,
)
from congress_docmeta.eval_blind import score
from congress_docmeta.schema_v4 import MAX_PERSONAS

_CTX = {"filename": "CHRG-118hhrg54321.pdf", "text": "HEARING BEFORE THE COMMITTEE ON OVERSIGHT. WITNESSES"}


def _person(i: int, role: str, etype: str) -> dict[str, Any]:
    return {"name": f"Pat Lastname{i:02d}", "role": role, "entity_type": etype}


def _transcript(personas: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "usable",
        "text_quality": "native",
        "chamber": "house",
        "congress": 118,
        "primary_kind": "hearing_transcript",
        "personas": personas,
        "composed_title": "Hearing on Federal Oversight",
        "gist": "The committee hears witnesses on federal oversight.",
        "topics": ["oversight"],
    }


def _leaders_and_witnesses(n_people: int) -> list[dict[str, Any]]:
    leaders = [_person(90, "chair", "member"), _person(91, "ranking_member", "member")]
    return leaders + [_person(i, "witness", "non_gov_person") for i in range(n_people - len(leaders))]


def _roster_dump() -> list[dict[str, Any]]:
    """Members read off a masthead, written as a model writes them: in floor roles."""
    return [_person(i, "questioner", "member") for i in range(ROSTER_LEAK_MEMBER_LIMIT_V6 + 1)]


def test_roster_shaped_members_are_members_outside_a_list_role() -> None:
    people = [
        _person(0, "chair", "member"),
        _person(1, "questioner", "member"),
        _person(2, "witness", "member"),  # a Member testifying
        _person(3, "cosponsor", "member"),
        _person(4, "signatory", "member"),
        _person(5, "recipient", "member"),
        _person(6, "author_or_speaker", "non_gov_person"),
    ]
    assert [p["name"] for p in roster_shaped_members_v6(people)] == ["Pat Lastname00", "Pat Lastname01"]
    assert roster_shaped_members_v6(None) == []


def test_router_flags_a_roster_not_a_full_witness_list() -> None:
    full = score_docmeta_anomalies_v6(_transcript(_leaders_and_witnesses(MAX_PERSONAS)), dict(_CTX))
    assert "persona_roster_leak" not in full["anomaly_codes"]

    dump = score_docmeta_anomalies_v6(_transcript(_roster_dump()), dict(_CTX))
    assert "persona_roster_leak" in dump["anomaly_codes"]


def test_scorer_counts_roster_spam_the_way_the_router_does() -> None:
    gold = _transcript(_leaders_and_witnesses(MAX_PERSONAS))
    exact = score([gold], [gold], [True])["metrics"]
    assert exact["roster_spam_docs"] == 0
    assert exact["personas_name_f1"] == 100.0

    assert score([_transcript(_roster_dump())], [gold], [True])["metrics"]["roster_spam_docs"] == 1

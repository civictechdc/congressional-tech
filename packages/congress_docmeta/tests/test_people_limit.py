"""The people limit (`schema_v4.MAX_PERSONAS`) and the roster guard that stopped depending on it (ct-bult)."""

from __future__ import annotations

import copy
import json
from typing import Any

import jsonschema
import pytest

from congress_docmeta.anomaly_router_v6 import (
    ROSTER_LEAK_MEMBER_LIMIT_V6,
    roster_shaped_members_v6,
    score_docmeta_anomalies_v6,
)
from congress_docmeta.compact_wire_v6 import (
    DOCMETA_V6_COMPACT_SCHEMA_OBJ,
    SYS_DOCMETA_V6_COMPACT,
    build_doc_kind_compact_schema_v6,
    encode_v4_to_compact_v6,
    expand_compact_json_str_to_v4,
)
from congress_docmeta.eval_blind import score
from congress_docmeta.grammar_router_ane_v6 import build_doc_kind_set_schema_v6
from congress_docmeta.parquet_runner_v6 import build_excluded_kind_schema_v6
from congress_docmeta.prompt_v4 import SYS_DOCMETA_V4, validate_v4
from congress_docmeta.pythonic_v5 import canonicalize_docmeta_v4, validate_docmeta_v4
from congress_docmeta.pythonic_v6 import build_doc_kind_schema_v6
from congress_docmeta.schema_v4 import MAX_PERSONAS, SCHEMA_OBJ
from congress_docmeta.training_pairs import WIRE_CONFIG

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


def test_router_flags_a_list_over_the_cap_but_not_a_full_cosponsor_line() -> None:
    bill = {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "bill_or_draft",
        "personas": [_person(0, "sponsor", "member")] + [_person(i, "cosponsor", "member") for i in range(1, MAX_PERSONAS)],
        "composed_title": "A bill to rename a post office",
        "gist": "Designates a post office building.",
        "topics": ["postal service"],
    }
    assert "persona_roster_leak" not in score_docmeta_anomalies_v6(bill, dict(_CTX))["anomaly_codes"]

    over = score_docmeta_anomalies_v6(bill, {**_CTX, "raw_persona_count": MAX_PERSONAS + 1})
    assert "persona_roster_leak" in over["anomaly_codes"]


# --- the format: 26 people, and nothing else about it moved ------------------------------------------------------


def _witness(i: int) -> dict[str, Any]:
    return {
        "name": f"Witness Person{i}",
        "title": "Director",
        "org": f"Example Institute {i}",
        "panel": "Panel I" if i < 4 else "Panel II",
        "role": "witness",
        "entity_type": "non_gov_person",
    }


def _hearing(n_witnesses: int) -> dict[str, Any]:
    """A transcript label in canonical key order: chair, ranking member, then the printed witness list."""
    return {
        "status": "usable",
        "text_quality": "native",
        "verbatim_title": "OVERSIGHT OF FEDERAL GRANT PROGRAMS",
        "chamber": "house",
        "congress": 117,
        "committees": ["Committee on Oversight and Reform"],
        "event_type": "hearing",
        "event_date": "2021-04-15",
        "primary_kind": "hearing_transcript",
        "personas": [
            {"name": "Alex Chairperson", "role": "chair", "entity_type": "member"},
            {"name": "Sam Ranking", "role": "ranking_member", "entity_type": "member"},
        ]
        + [_witness(i) for i in range(n_witnesses)],
        "composed_title": "Oversight of Federal Grant Programs",
        "gist": "Eight witnesses testify on how federal grant programs are overseen.",
        "topics": ["grants", "oversight"],
    }


_COMPACT = jsonschema.Draft202012Validator(DOCMETA_V6_COMPACT_SCHEMA_OBJ)


def test_the_limit_is_26_everywhere_the_schema_reaches() -> None:
    # Moving this number is a contract change (prompt, grammar, labels, decode budget); do it on purpose.
    assert MAX_PERSONAS == 26
    assert SCHEMA_OBJ["properties"]["personas"]["maxItems"] == MAX_PERSONAS
    assert DOCMETA_V6_COMPACT_SCHEMA_OBJ["properties"]["ps"]["maxItems"] == MAX_PERSONAS
    # The per-document grammars are built from copies of the schema; each keeps the limit.
    assert build_doc_kind_compact_schema_v6("hearing_transcript")["properties"]["ps"]["maxItems"] == MAX_PERSONAS
    assert build_doc_kind_schema_v6("hearing_transcript")["properties"]["personas"]["maxItems"] == MAX_PERSONAS
    assert build_doc_kind_set_schema_v6(["witness_list"])["properties"]["personas"]["maxItems"] == MAX_PERSONAS
    assert build_excluded_kind_schema_v6("other")["properties"]["personas"]["maxItems"] == MAX_PERSONAS
    # The prompts the model reads state the same number, and the training hand-over records it.
    assert f"ps(<={MAX_PERSONAS}: n," in SYS_DOCMETA_V6_COMPACT
    assert f"PERSONAS <= {MAX_PERSONAS}:" in SYS_DOCMETA_V4 and f"personas ([]<={MAX_PERSONAS}:" in SYS_DOCMETA_V4
    assert WIRE_CONFIG["max_personas"] == MAX_PERSONAS


def test_26_people_validate_and_round_trip_through_the_compact_wire() -> None:
    label = _hearing(MAX_PERSONAS - 2)
    assert len(label["personas"]) == 26
    assert validate_docmeta_v4(label) == (True, None)
    assert validate_v4(label) == (True, None)  # jsonschema, a second validator
    assert canonicalize_docmeta_v4(copy.deepcopy(label)) == label  # nothing cut

    compact = encode_v4_to_compact_v6(label)
    assert len(compact["ps"]) == 26
    _COMPACT.validate(compact)
    expanded, _ = expand_compact_json_str_to_v4(json.dumps(compact, separators=(",", ":")))
    assert expanded == label


def test_27_people_are_refused_by_every_validator_and_cut_to_26() -> None:
    label = _hearing(MAX_PERSONAS - 1)
    assert len(label["personas"]) == 27
    ok, err = validate_docmeta_v4(label)
    assert not ok and "maxItems 26" in err
    assert validate_v4(label)[0] is False
    with pytest.raises(jsonschema.ValidationError):
        _COMPACT.validate(encode_v4_to_compact_v6(label))
    cut = canonicalize_docmeta_v4(copy.deepcopy(label))
    assert cut["personas"] == label["personas"][:26]


# `_hearing(8)` as origin/main's compact_wire_v6 encoded it before ct-bult (limit 10): the wire bytes of a label
# that was valid under the old limit must not move.
_OLD_TEN_PERSON_WIRE = (
    '{"vt":"OVERSIGHT OF FEDERAL GRANT PROGRAMS","ch":"house","cg":117,"cm":["Committee on Oversight and Reform"],'
    '"et":"hearing","ed":"2021-04-15","pk":"hearing_transcript","ps":[{"n":"Alex Chairperson","r":"chair","e":"member"},'
    '{"n":"Sam Ranking","r":"ranking_member","e":"member"},'
    + ",".join(
        f'{{"n":"Witness Person{i}","t":"Director","o":"Example Institute {i}","pn":"Panel {"I" if i < 4 else "II"}",'
        f'"r":"witness","e":"non_gov_person"}}'
        for i in range(8)
    )
    + '],"ct":"Oversight of Federal Grant Programs","gi":"Eight witnesses testify on how federal grant programs are '
    'overseen.","tp":["grants","oversight"]}'
)


def test_a_ten_person_label_from_before_the_change_is_unchanged() -> None:
    label = _hearing(8)
    assert len(label["personas"]) == 10
    assert validate_docmeta_v4(label) == (True, None)
    assert validate_v4(label) == (True, None)
    assert canonicalize_docmeta_v4(copy.deepcopy(label)) == label
    wire = json.dumps(encode_v4_to_compact_v6(label), separators=(",", ":"), ensure_ascii=False)
    assert wire == _OLD_TEN_PERSON_WIRE
    assert expand_compact_json_str_to_v4(wire)[0] == label

"""Assembly validates each changed record and every final graph relationship."""
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from committee_explorer.assemble import Assembly
from committee_meeting import Catalog
from committee_meeting.common import Identifier, Model, Ref
from committee_meeting.issues import DataIssue
from committee_meeting.meetings import Appearance, Meeting, RecordedName
from committee_meeting.provenance import Citation, FieldEvidence, Provenance, SourceRecord


NOW = datetime(2026, 9, 27, tzinfo=UTC)


def evidence(identifier="source"):
    return Provenance(basis="reported", citations=(Citation(source=Ref(kind="source_record", id=identifier)),))


def source(identifier="source"):
    return SourceRecord(id=identifier, provider="fixture", identifier=Identifier(scheme="fixture", value=identifier), payload={"value": identifier})


def meeting(**updates):
    return Meeting(id="meeting", title="Retained hearing", congress=119, provenance=evidence(), **updates)


def test_unsafe_model_copy_cannot_bypass_record_or_nested_validators():
    original = meeting()
    for record in (original.model_copy(update={"congress": 0}), original.model_copy(update={"provenance": original.provenance.model_copy(update={"citations": ()})})):
        with pytest.raises(ValueError):
            Assembly().add([record])


def test_direct_replacements_and_mapping_updates_also_validate():
    assembly = Assembly()
    assembly.add([source(), meeting()])
    key = ("meeting", "meeting")
    invalid = meeting().model_copy(update={"congress": 0})
    with pytest.raises(ValueError):
        assembly.records[key] = invalid
    with pytest.raises(ValueError):
        assembly.records.update({key: invalid})
    with pytest.raises(ValueError, match="identity"):
        assembly.records[("meeting", "wrong")] = meeting()
    assert assembly.records[key].congress == 119


def test_merge_is_validated_before_it_replaces_the_record():
    item = DataIssue(id="issue", subject=Ref(kind="meeting", id="meeting"), category="unverified", summary="Check needed", detected_at=NOW, provenance=evidence())
    assembly = Assembly()
    assembly.add([item])
    with pytest.raises(ValueError, match="closed issues require"):
        assembly.add([item.model_copy(update={"status": "resolved"})])
    assert assembly.records[("data_issue", "issue")].status == "open"


def test_finish_reuses_individually_validated_instances_and_runs_graph_check(monkeypatch):
    assembly = Assembly()
    assembly.add([source(), meeting()])
    record = assembly.records[("meeting", "meeting")]
    # Constructing a second whole Catalog would revalidate/copy every instance.
    monkeypatch.setattr(Catalog, "__init__", lambda *args, **kwargs: pytest.fail("finish revalidated the full catalog"))
    catalog = assembly.finish()
    assert catalog.records[0] is record
    assert catalog.sources[0] is assembly.sources[("source_record", "source")]
    assert catalog.schema_version and catalog.scope == "complete"


def test_assembled_models_share_field_name_sets_without_changing_any_dump():
    # Each instance's own set was nearly half of an assembled record's memory.
    first, second = meeting(), meeting().model_copy(update={"id": "other"})
    dumps = {r.id: (r.model_dump_json(), r.model_dump_json(exclude_unset=True)) for r in (first, second)}
    assembly = Assembly()
    assembly.add([source(), first, second, meeting(chamber="house").model_copy(update={"id": "third"})])
    one, two, three = (assembly.records["meeting", identity] for identity in ("meeting", "other", "third"))
    assert one.__pydantic_fields_set__ is two.__pydantic_fields_set__
    assert one.provenance.citations[0].source.__pydantic_fields_set__ is two.provenance.citations[0].source.__pydantic_fields_set__
    assert three.model_fields_set == one.model_fields_set | {"chamber"}
    for record in (one, two):
        assert (record.model_dump_json(), record.model_dump_json(exclude_unset=True)) == dumps[record.id]
    shared = set(one.model_fields_set)
    # Updates copy the shared set first; frozen models reject assignment before touching it.
    assert "chamber" in one.model_copy(update={"chamber": "senate"}).model_fields_set
    with pytest.raises(ValidationError):
        one.chamber = "senate"
    assert one.model_fields_set == shared == two.model_fields_set and "chamber" not in shared
    assert first.model_fields_set == shared  # The caller's instances are untouched.
    # Sharing is safe only while no model can be assigned to after validation.
    pending, models = [Model], []
    while pending:
        models.append(cls := pending.pop())
        pending.extend(cls.__subclasses__())
    assert len(models) > 20 and all(cls.model_config.get("frozen") for cls in models)


def test_complete_graph_validator_still_rejects_missing_and_wrong_ownership():
    missing = Assembly()
    missing.add([meeting()])
    with pytest.raises(ValueError, match="missing source_record/source"):
        missing.finish()
    wrong = Assembly()
    wrong.add([source(), meeting(), Appearance(id="appearance", meeting=Ref(kind="meeting", id="elsewhere"), name=RecordedName(display="Alex Smith"), provenance=evidence())])
    with pytest.raises(ValueError, match="missing meeting/elsewhere"):
        wrong.finish()


def test_merge_keeps_disagreement_and_produces_valid_conflict_issue():
    assembly = Assembly(ids=lambda kind,key: kind+":"+key, now=NOW)
    assembly.add([source(), meeting()])
    assembly.add([meeting().model_copy(update={"title": "Revised title"})])
    catalog = assembly.finish()
    selected = next(record for record in catalog.records if record.kind == "meeting")
    issue = next(record for record in catalog.records if record.kind == "data_issue")
    assert selected.title == "Revised title" and selected.field_evidence[0].alternatives[0].value == "Retained hearing"
    assert issue.category == "conflicting" and issue.field_path == "/title"


def test_empty_incoming_value_does_not_supply_evidence_for_retained_value():
    assembly = Assembly()
    assembly.add([source(), source('empty'), meeting()])
    assembly.add([meeting().model_copy(update={'title': None, 'field_evidence': (
        FieldEvidence(path='/title', selected=evidence('empty'), selection_reason='Source has no title.'),)})])
    retained = assembly.records['meeting', 'meeting']
    assert retained.title == 'Retained hearing'
    assert not any(field.path == '/title' for field in retained.field_evidence)
    assembly.finish()


def test_spilled_records_and_sequence_stream_by_kind_and_json_dicts():
    from committee_explorer.assemble import SpilledRecordSequence, _SpilledRecords

    assembly = Assembly(ids=lambda kind, key: kind + ":" + key, now=NOW)
    assert isinstance(assembly.records, _SpilledRecords)
    assembly.add([
        source(),
        meeting().model_copy(update={"id": "m1", "title": "First hearing"}),
        meeting().model_copy(update={"id": "m2", "title": "Second hearing"}),
        Appearance(
            id="a1",
            meeting=Ref(kind="meeting", id="m1"),
            name=RecordedName(display="Alex Smith"),
            provenance=evidence(),
        ),
    ])
    assembly.add([meeting().model_copy(update={"id": "m1", "title": "First hearing revised"})])
    assert ("meeting", "m1") in assembly.records._conflict_keys
    assert ("meeting", "m2") not in assembly.records._conflict_keys

    catalog = assembly.finish()
    assert isinstance(catalog.records, SpilledRecordSequence)
    assert [r.id for r in catalog.records.iter_kind("meeting")] == ["m1", "m2"]
    assert [r.id for r in catalog.records.iter_kind("appearance")] == ["a1"]
    assert len(list(catalog.records.iter_kind("data_issue"))) == 1
    json_dicts = list(catalog.records.iter_json_dicts())
    assert [d["kind"] for d in json_dicts] == ["meeting", "meeting", "appearance", "data_issue"]
    assert catalog.records.get_by_key(("meeting", "m2")).title == "Second hearing"
    assert catalog.records.get_by_key(("meeting", "nonexistent")) is None

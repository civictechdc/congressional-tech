from datetime import datetime, timezone

from committee_explorer.assemble import Assembly
from committee_explorer.recovered import reuse_appearances
from committee_meeting.meetings import Appearance, RecordedName, Affiliation
from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext


def context(provider):
    return AdapterContext(datetime.now(timezone.utc), 'input', provider, lambda kind, key: kind + key)


def test_recovered_copy_keeps_rich_source_fields_and_evidence():
    house = context('docs.house.gov'); recovery = context('recovered-witnesses')
    source = house.source('event', {'witnesses': []})
    derived = recovery.source('copy', {'source': 'docs.house.gov'})
    original = Appearance(id='original', meeting=Ref(kind='meeting', id='meeting'),
        name=RecordedName(display='Ms. Laura Eskenazi'), roles=('witness',),
        affiliation=Affiliation(position='Principal Deptuy Vice Chairman', organization_name="Board of Veterans’ Appeals", on_behalf_of='VA'),
        provenance=house.evidence(source))
    copy = original.model_copy(update={'id': 'copy', 'affiliation': original.affiliation.model_copy(update={'on_behalf_of': None}), 'provenance': recovery.evidence(derived)})
    assembly = Assembly(); assembly.add([source, original])
    assembly.add(reuse_appearances([derived, copy], assembly))
    appearances = [v for v in assembly.records.values() if v.kind == 'appearance']
    assert len(appearances) == 1
    assert appearances[0].id == 'original'
    assert appearances[0].affiliation.on_behalf_of == 'VA'
    assert len(appearances[0].provenance.citations) == 2
    assert not appearances[0].field_evidence


def test_ambiguous_same_named_appearances_stay_separate():
    source_context = context('docs.house.gov'); recovered_context = context('recovered-witnesses')
    source = source_context.source('event', {})
    recovered = recovered_context.source('copy', {'source': 'docs.house.gov'})
    original = Appearance(id='one', meeting=Ref(kind='meeting', id='meeting'), name=RecordedName(display='Alex Smith'), provenance=source_context.evidence(source))
    assembly = Assembly(); assembly.add([source, original, original.model_copy(update={'id': 'two'})])
    copy = original.model_copy(update={'id': 'copy', 'provenance': recovered_context.evidence(recovered)})
    assembly.add(reuse_appearances([recovered, copy], assembly))
    assert len([r for r in assembly.records.values() if r.kind == 'appearance']) == 3

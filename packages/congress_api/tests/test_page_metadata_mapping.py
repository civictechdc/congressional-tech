"""Declared page metadata fills cited fields and never decides meetings, people or identity.

Fixtures indian-affairs, ways-and-means and banking-powell are trimmed real pages. The
retained sample has no canonical or og:url on admin-intelligence.house.gov (one body only
mentions the host in an author ID), so that case is synthetic. Real material-page
metadata has no supplier until ct-pocg: these prove the mapping, not its coverage.
"""
from pathlib import Path

from committee_meeting.common import Ref, ReportedTime
from committee_meeting.materials import DocumentDetails, Material
from congress_api.adapters.common import AdapterContext, material_records
from congress_api.adapters.page_metadata import enrich_material, main_content_representation, metadata_source, page_source
from congress_api.adapters.senate import records
from congress_api.models.html_metadata import MainContentRef
from congress_api.parsers.html_metadata import page_facts, read_html_metadata
from test_explorer_senate_adapter import NOW, PAGE, context, of_kind, page

FIXTURES = Path(__file__).parent / 'fixtures/html_metadata'
PAGE_URL = 'https://committee.example.gov/page'


def metadata(name):
    return read_html_metadata((FIXTURES / name).read_bytes())


def supplied(**pages):
    return AdapterContext(now=NOW, input_id='senate-input', provider='senate.committee', ids=lambda kind, key: kind + ':' + key, page_metadata=pages)


def resolve(document, pointer):
    for part in pointer.split('/')[1:]:
        document = document[int(part)] if isinstance(document, list) else document[part.replace('~1', '/').replace('~0', '~')]
    return document


def material_row(ctx, name='ways-and-means.html', **fields):
    evidence = ctx.evidence(ctx.source('page', {'x': 1}))
    rows = material_records(ctx, evidence, 'key', urls=[PAGE_URL], details=DocumentDetails(category='unknown'), **fields)
    return rows, next(row for row in rows if row.kind == 'material')


def adapt_senate(ctx, saved):
    state = {'example.senate.gov': {'listings': {PAGE: ['2026-09-20', 'Evidence hearing']}, 'pages': {PAGE: saved}}}
    return list(records(state, ctx, meetings={(119, 'senate', '12'): Ref(kind='meeting', id='meeting-12')}))


def test_no_metadata_leaves_adapter_output_identical():
    saved = page()
    default, empty = adapt_senate(context(), saved), adapt_senate(supplied(), saved)
    assert [row.model_dump() for row in default] == [row.model_dump() for row in empty]


def test_no_metadata_leaves_material_records_identical():
    plain = context()
    evidence = plain.evidence(plain.source('page', {'x': 1}))
    assert all(row.model_dump().get('description') is None for row in material_records(plain, evidence, 'key', urls=[PAGE_URL]) if row.kind == 'material')


def test_indian_affairs_modified_time_is_the_source_not_the_event():
    saved = page()
    ctx = supplied(**{PAGE: metadata('indian-affairs.html')})
    rows, baseline = adapt_senate(ctx, saved), adapt_senate(context(), saved)
    source = next(row for row in of_kind(rows, 'source_record') if row.identifier.value.startswith('senate-page|'))
    plain = next(row for row in of_kind(baseline, 'source_record') if row.identifier.value.startswith('senate-page|'))
    assert source.source_modified_at.date.isoformat() == '2025-04-01'
    assert source.payload == plain.payload and source.id == plain.id  # the page source is untouched
    assert [row.model_dump() for row in of_kind(rows, 'meeting')] == [row.model_dump() for row in of_kind(baseline, 'meeting')]
    assert any(row.identifier.value.startswith('html-metadata|') for row in of_kind(rows, 'source_record'))


def test_banking_cards_never_become_appearances():
    facts = metadata('banking-powell.html')
    names = {fact.value['properties']['name'][0] for fact in page_facts(facts) if fact.field == 'person_card'}
    assert {'Mike Crapo', 'Chairman Sherrod Brown', 'The Honorable Jerome H. Powell'} == names
    saved = page()
    with_metadata = adapt_senate(supplied(**{PAGE: facts}), saved)
    without = adapt_senate(context(), saved)
    assert [row.model_dump() for row in of_kind(with_metadata, 'appearance')] == [row.model_dump() for row in of_kind(without, 'appearance')]
    assert not of_kind(with_metadata, 'person')
    assert not any('Crapo' in str(row.model_dump()) for row in of_kind(with_metadata, 'appearance'))


def test_ways_and_means_section_retained_admin_not_a_person_published_cited():
    facts = metadata('ways-and-means.html')
    rows, material = material_row(supplied(**{PAGE_URL: facts}), title='Advisory')
    assert material.source_document_groups == ('Hearing Advisory',)
    assert material.published_at.date.isoformat() == '2013-06-13'
    assert material.description.startswith('House Ways and Means Health Subcommittee')
    assert not [row for row in rows if row.kind in {'person', 'appearance'}]
    source = next(row for row in rows if row.kind == 'source_record')
    field = next(field for field in material.field_evidence if field.path == '/published_at')
    assert resolve(source.payload, field.selected.citations[0].selector) == '2013-06-13T00:00:00+00:00'
    assert material.details.category == 'unknown'


def test_declared_other_host_raises_an_issue_and_leaves_identity_alone():
    # Synthetic: no real og:url on this host in the sample.
    body = b'<html><head><meta property="og:url" content="https://admin-intelligence.house.gov/x"><title>t</title></head></html>'
    ctx = supplied(**{PAGE_URL: read_html_metadata(body)})
    rows, material = material_row(ctx)
    issue, = [row for row in rows if row.kind == 'data_issue']
    assert 'admin-intelligence.house.gov' in issue.explanation
    plain_rows, plain = material_row(supplied())
    assert material.id == plain.id and material.identifiers == plain.identifiers == ()


def test_same_host_and_relative_declarations_raise_no_issue():
    rows, _ = material_row(supplied(**{PAGE_URL: read_html_metadata(b'<html><head><link rel="canonical" href="/x"><meta property="og:url" content="https://www.committee.example.gov/y"></head></html>')}))
    assert not [row for row in rows if row.kind == 'data_issue']


def test_date_only_and_unzoned_precision_is_preserved():
    body = b'<html><head><meta property="article:published_time" content="2025-03-01"><meta property="article:modified_time" content="2025-04-01T12:30:00"></head></html>'
    _, material = material_row(supplied(**{PAGE_URL: read_html_metadata(body)}))
    assert material.published_at.precision == 'day' and material.published_at.time is None
    assert material.source_modified_at.timezone is None and material.source_modified_at.time.hour == 12 and material.source_modified_at.original == '2025-04-01T12:30:00'


def test_unparseable_declared_date_stays_in_the_source_only():
    _, material = material_row(supplied(**{PAGE_URL: read_html_metadata(b'<html><head><meta property="article:published_time" content="soon"></head></html>')}))
    assert material.published_at is None


def test_empty_title_site_and_template_descriptions_are_rejected():
    def described(meta, title='My title'):
        body = f'<html><head><meta property="og:site_name" content="Site Name">{meta}</head></html>'.encode()
        return material_row(supplied(**{PAGE_URL: read_html_metadata(body)}), title=title)[1].description
    assert described('<meta property="og:description" content=" ">') is None
    assert described('<meta property="og:description" content="my TITLE">') is None
    assert described('<meta property="og:description" content="Site Name">') is None
    assert described('<meta property="og:description" content="Official Publications from the U.S. Government Publishing Office.">') is None
    assert described('<meta name="description" content="A real summary">') == 'A real summary'
    website = '<script type="application/ld+json">{"@type":"WebSite","description":"Whole site"}</script>'
    assert described(website) is None


def test_description_order_and_disagreement_is_kept_as_an_alternative():
    body = (b'<html><head><meta name="description" content="Meta text"><meta property="og:description" content="OG text">'
            b'<script type="application/ld+json">{"@type":"Article","description":"LD text"}</script></head></html>')
    _, material = material_row(supplied(**{PAGE_URL: read_html_metadata(body)}))
    assert material.description == 'OG text'
    field = next(field for field in material.field_evidence if field.path == '/description')
    assert [alternative.value for alternative in field.alternatives] == ['LD text', 'Meta text']


def test_existing_values_win_and_disagreement_is_cited():
    ctx = supplied()
    facts = read_html_metadata(b'<html><head><meta property="article:published_time" content="2020-01-02"></head></html>')
    source = metadata_source(ctx, PAGE_URL, facts)
    original = Material(id='m', published_at=ReportedTime(date='2021-05-05', original='2021-05-05'), source_document_groups=('Publisher',),
                        description='Publisher text', provenance=ctx.evidence(source))
    material = enrich_material(ctx, original, facts, source)
    assert material.published_at == original.published_at and material.source_document_groups == ('Publisher',)
    field, = [field for field in material.field_evidence if field.path == '/published_at']
    assert field.alternatives[0].value['original'] == '2020-01-02'


def test_page_source_payload_and_id_are_stable_and_existing_modified_time_kept():
    ctx = supplied(**{PAGE_URL: metadata('indian-affairs.html')})
    source = ctx.source('page', {'a': 1}, PAGE_URL)
    updated, extra = page_source(ctx, PAGE_URL, source)
    assert updated.id == source.id and updated.payload == source.payload
    assert extra[0].identifier.value == 'html-metadata|' + extra[0].payload['body_sha256']
    kept = source.model_copy(update={'source_modified_at': ReportedTime(date='2000-01-01', original='2000-01-01')})
    assert page_source(ctx, PAGE_URL, kept)[0].source_modified_at.date.isoformat() == '2000-01-01'


def test_main_content_is_an_ordinary_representation():
    ctx = supplied()
    source = ctx.source('s', {'x': 1})
    version = next(row for row in material_row(ctx)[0] if row.kind == 'material_version')
    reference = MainContentRef(body_sha256='0' * 64, reader_version='v', outcome='marked', selector='/html/body/div', property='content:encoded',
                               text_sha256='a' * 64, text_bytes=5, snippet='hello')
    row = main_content_representation(ctx, 'k', version, reference, source)
    assert (row.media_type, row.sha256, row.byte_size, row.retained) == ('text/plain', 'a' * 64, 5, None)
    assert (row.provenance.citations[0].selector_type, row.provenance.citations[0].selector) == ('xpath', '/html/body/div')
    assert main_content_representation(ctx, 'k', version, reference.model_copy(update={'text_sha256': None}), source) is None


def test_every_fact_pointer_resolves_to_its_value():
    for name in ('all-formats.html', 'indian-affairs.html', 'ways-and-means.html', 'banking-powell.html'):
        facts = metadata(name)
        document = facts.source_dict()
        found = page_facts(facts)
        assert found
        for fact in found:
            assert resolve(document, fact.path) == fact.value, fact


# Official-event listing rows: a source-only meeting's clock and room.
def schedule(details, start='2026-09-20', correction=None):
    from congress_api.adapters.common import reported_time
    from congress_api.adapters.senate import listed_schedule
    return listed_schedule(context(), 'example.senate.gov', {'listing_details': {PAGE: details}}, PAGE, reported_time(start), correction)


def test_listing_row_adds_displayed_clock_and_room_when_the_day_matches():
    start, location, fields, source = schedule({'date_text': '09/20/26', 'time': '03:00PM', 'room': 'SD-138',
                                                'encoded_start': '2026-09-20T03:00', 'time_evidence': 'displayed_conflicts_encoded'})
    assert (start.time.hour, start.time.minute, start.timezone, start.original) == (15, 0, None, '03:00PM')
    assert location.label == 'SD-138' and source.payload['room'] == 'SD-138'
    assert fields[0].alternatives[0].value == '2026-09-20T03:00'


def test_listing_row_never_moves_the_day_or_selects_an_ambiguous_clock():
    other_day = schedule({'date_text': '09/21/26', 'time': '03:00PM', 'room': 'SD-138'})
    assert other_day[0].date.isoformat() == '2026-09-20' and other_day[0].time is None and other_day[1:] == (None, (), None)
    ambiguous = schedule({'date_text': '09/20/26', 'encoded_start': '2026-09-20T03:00', 'time_evidence': 'encoded_only_ambiguous', 'room': 'SD-138'})
    assert ambiguous[0].time is None and ambiguous[1] is None


def test_rows_saved_before_date_text_change_nothing():
    assert schedule({'time': '10:00 AM', 'room': 'S-116'})[1:] == (None, (), None)
    assert schedule({'date_text': '09/20/26', 'time': '10:00AM'}, correction={'date': 'x'})[1:] == (None, (), None)

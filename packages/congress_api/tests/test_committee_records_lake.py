"""`committee_records` keeps every amendment and vote link House meeting XML states."""
from congress_api.lake import committee_records

SHA = 'cd' * 32
XML = b"""<committee-meeting meeting-id="HMKP00-20250101-SD001" update-date="2025-01-02T03:04:05"/>"""


def document(code, url, number='1', extra=''):
    file = f'<files><file doc-url="{url}"/></files>' if url else ''
    return (f'<meeting-document type="{code}"><description>Text</description><legis-num>H.R. 1</legis-num>'
            f'<filename-metadata><amdt-num>{number}</amdt-num><vote-num>{number}</vote-num><bioguideID>A000001</bioguideID>'
            f'<amdt-type>Republican</amdt-type>{extra}</filename-metadata>{file}</meeting-document>')


def meeting(*documents, meeting_id='HMKP00-CR-112233'):
    return (f'<committee-meeting meeting-id="{meeting_id}" update-date="2025-01-02T03:04:05" meeting-status="1">'
            '<meeting-documents>' + ''.join(documents) + '</meeting-documents></committee-meeting>').encode()


def build(payload):
    return committee_records.build_row(SHA, 'house_xml', payload, parser_version='v')


def test_amendment_and_vote_are_kept_as_document_links():
    row = build(meeting(document('CA', 'https://docs.house.gov/a.pdf'), document('CV', 'https://docs.house.gov/v.pdf', '4'), document('HW', 'https://docs.house.gov/w.pdf')))
    assert row['updated'] == '2025-01-02T03:04:05'
    assert [(r['ordinal'], r['kind'], r['number'], r['url']) for r in row['records']] == [
        (0, 'amendment', '1', 'https://docs.house.gov/a.pdf'), (1, 'vote', '4', 'https://docs.house.gov/v.pdf')]
    assert row['records'][0]['sponsor_bioguide'] == 'A000001' and row['records'][0]['bill'] == 'H.R. 1'


def test_duplicate_amendments_are_retained_with_their_own_ordinals():
    same = document('CA', 'https://docs.house.gov/a.pdf')
    assert [r['ordinal'] for r in build(meeting(same, same))['records']] == [0, 1]


def test_amendment_without_a_url_is_retained():
    records = build(meeting(document('HA', '')))['records']
    assert len(records) == 1 and records[0]['url'] is None and records[0]['kind'] == 'amendment'


def test_other_xml_roots_give_an_empty_row_never_parsed_again():
    for payload in (b'<witness-list/>', b'not xml', b''):
        row = build(payload)
        assert row['status'] == 'completed' and row['records'] == [] and row['event_id'] is None


def test_same_bytes_same_rows_and_schema():
    payload = meeting(document('CA', 'https://docs.house.gov/a.pdf'))
    assert build(payload) == build(payload)
    assert committee_records.table([build(payload)]).schema.equals(committee_records.ARROW_SCHEMA)

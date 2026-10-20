"""A saved committee page is a source record when its page was recorded."""
from congress_api.retention.document_index import apply_capture_record_role, fill_document_kind


HEARING = 'https://www.appropriations.senate.gov/hearings/forest-service'


def page(**extra):
    row = {
        'source_url': HEARING,
        'record_role': ['document'],
        'media_type': ['text/html;charset=UTF-8'],
        'source_page_url': [HEARING, 'https://api.congress.gov/v3/committee-meeting/117/senate/332414'],
        'source_page_title': ['Hearing'],
        'source_meeting_type': ['Meeting'],
        'source_congress': ['117'],
        'source_chamber': ['Senate'],
    }
    row.update(extra)
    return row


def test_recorded_hearing_page_becomes_a_source_record():
    row = page()
    apply_capture_record_role(row)
    fill_document_kind(row)
    assert row['record_role'] == ['source-record']
    assert row['source_record_type'] == ['committee-hearing-page']
    assert row['document_kind'] is None
    assert row['source_congress'] == ['117']
    assert row['source_chamber'] == ['Senate']


def test_meeting_title_names_a_meeting_page():
    row = page(source_page_title=['Business meeting'], source_meeting_type=None)
    apply_capture_record_role(row)
    assert row['source_record_type'] == ['committee-meeting-page']


def test_hearing_path_without_a_recorded_page_stays_a_document():
    row = page(source_page_url=['https://www.appropriations.senate.gov/hearings'], source_page_title=None, source_meeting_type=None)
    apply_capture_record_role(row)
    assert row['record_role'] == ['document']
    assert 'source_record_type' not in row


def test_linked_document_is_not_the_hearing_page():
    row = page(source_url='https://www.appropriations.senate.gov/download/statement.pdf', media_type=['application/pdf'])
    apply_capture_record_role(row)
    assert row['record_role'] == ['document']
    assert 'source_record_type' not in row


def test_existing_document_kind_keeps_the_file_a_document():
    row = page(document_kind=['witness-statement'])
    apply_capture_record_role(row)
    assert row['record_role'] == ['document']
    assert 'source_record_type' not in row

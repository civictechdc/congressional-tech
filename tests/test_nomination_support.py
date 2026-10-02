"""A paired Judiciary nomination-page link can establish support purpose, not letter form."""
import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index

PAGE = 'https://www.judiciary.senate.gov/committee-activity/hearings/05/17/2023/nominations'
LINK = 'https://www.judiciary.senate.gov/download/aramayo-support-for-de-alba'


def occurrence(label='Assistant District Attorney Aramayo Support for de Alba', **fields):
    return dict(source_original_page_url=[PAGE], source_page_title=['Nominations'],
                source_link_url=[LINK], source_link_label=[label],
                source_publisher_committee_code=['ssju00'], source_occurrence_scope=['anchor'], **fields)


def classify(observation=None, **fields):
    row = dict(source_occurrences=[occurrence() if observation is None else observation], **fields)
    index.fill_document_kind(row)
    return row


@pytest.mark.parametrize('label', [
    'Aramayo Support for de Alba', 'Aramayo_support_for_de_Alba',
    'Aramayo-support-for-de-Alba', 'AramayosupportfordeAlba',
    'Aramayo Support_-_for de Alba', 'Aramayo SUPPORT - FOR de Alba',
    'Aramayo in support of de Alba', 'Former Opposing Federal Prosecutors Support for Hwang',
])
def test_support_spelling_variants_use_the_existing_filename_reader(label):
    row = classify(occurrence(label))
    assert row['document_kind'] == row['document_family'] == ['nomination-support']
    assert row['document_kind_source'] == ['source_context']


@pytest.mark.parametrize('title', ['Nominations', 'TIME AND ROOM CHANGE: Nominations',
    'LOCATION CHANGE: Nominations', 'The Nomination of the Honorable Pamela J...'])
def test_recognized_nomination_titles(title):
    observation = occurrence()
    observation['source_page_title'] = [title]
    assert classify(observation)['document_kind'] == ['nomination-support']


@pytest.mark.parametrize('kind,family', [('letter-of-support','letter'), ('statement','statement'),
                                      ('press-release','press-release')])
def test_specific_filename_forms_are_preserved_in_the_shared_family(kind, family):
    original = occurrence()
    row = classify(original, document_kind=[kind])
    assert row['document_kind'] == [kind]
    assert row['document_kind_source'] == ['filename']
    assert row['document_family'] == sorted([family, 'nomination-support'])
    assert row['source_occurrences'] == [original]


def test_known_content_and_native_types_stay_more_specific():
    assert classify(content_document_kind=['letter-of-support'])['document_kind'] == ['letter-of-support']
    native = occurrence(source_document_type=['Witness Statement'])
    row = classify(native)
    assert row['document_kind'] == ['witness-statement']
    assert row['document_kind_source'] == ['source_document_type']
    assert row['document_family'] == ['nomination-support', 'statement']


@pytest.mark.parametrize('label', ['Eisenberg Letter of Support - Colleagues',
    'ARTAU Letter of Support - Former GCs to FL Gov', 'Lee Letter of Support for Smith'])
def test_explicit_support_letter_labels_preserve_the_form(label):
    row = classify(occurrence(label))
    assert row['document_kind'] == ['letter-of-support']
    assert row['document_kind_source'] == ['source_link_label']
    assert row['document_family'] == ['letter', 'nomination-support']


def test_explicit_letter_label_takes_priority_over_another_generic_support_link():
    row = dict(source_occurrences=[occurrence(), occurrence('Eisenberg Letter of Support - Colleagues')])
    index.fill_document_kind(row)
    assert row['document_kind'] == ['letter-of-support']


@pytest.mark.parametrize('label', [
    'Dynatemp Support for S. 2754', 'Expressing support for H.R. 42',
    'Group Support for', 'Group opposition to Smith',
    'Group Support for Smith opposition to Jones',
    'Group support_forensic_tests', 'Group unsupported-format',
])
def test_absent_targets_opposition_and_legislative_references_abstain(label):
    assert classify(occurrence(label))['document_kind'] is None


@pytest.mark.parametrize('field,value', [
    ('source_original_page_url', ['https://www.epw.senate.gov/hearings/nominations']),
    ('source_original_page_url', ['https://www.judiciary.senate.gov.evil.test/committee-activity/hearings/nominations']),
    ('source_original_page_url', ['https://www.judiciary.senate.gov/news/press-releases/nominations']),
    ('source_original_page_url', ['https://api.congress.gov/v3/committee-meeting/118/senate/334142']),
    ('source_page_title', ['Oversight of the nominations process']),
    ('source_page_title', []),
    ('source_occurrence_scope', ['retained_url_aggregate']),
    ('source_link_label', []),
    ('source_association_basis', ['candidate_without_legacy_directory', 'publisher_redirect']),
])
def test_insufficient_or_unconfirmed_context_abstains(field, value):
    obs = occurrence()
    obs[field] = value
    assert classify(obs)['document_kind'] is None


def test_parent_and_support_label_must_belong_to_the_same_occurrence():
    a, b = occurrence('Attachment'), occurrence()
    b['source_original_page_url'] = ['https://www.epw.senate.gov/hearings/nominations']
    row = {**occurrence(), 'source_occurrences': [a, b]}
    index.fill_document_kind(row)
    assert row['document_kind'] is None
    flat = occurrence()
    index.fill_document_kind(flat)
    assert flat['document_kind'] is None


@pytest.mark.parametrize('role', ['source-record', 'capture-state', 'error-response'])
def test_source_and_failed_captures_are_not_promoted(role):
    row = classify(record_role=[role])
    assert row['document_kind'] is row['document_family'] is None


def test_publisher_redirect_preserves_support_context():
    row = classify(occurrence(source_association_basis=['publisher_redirect']))
    assert row['document_kind'] == ['nomination-support']


def test_rebuild_recomputes_context_and_does_not_cache_it_as_filename_meaning(tmp_path):
    (tmp_path/'indexes').mkdir()
    row = dict(filename='Aramayo Support for de Alba.pdf', source_url=LINK, body_key=None,
               source_occurrences=[occurrence()])
    index.write_filename_metadata(tmp_path, [row], workers=1)
    path = tmp_path/'indexes/document-filenames.parquet'
    first = pq.read_table(path)
    saved, = first.to_pylist()
    assert saved['document_kind'] == ['nomination-support']
    index.reindex_documents(tmp_path)
    same, = pq.read_table(path).to_pylist()
    assert same == saved
    # A full filename rebuild may reuse cached filename extraction. Context
    # must still disappear when its supporting occurrence is removed.
    clean = {**row, 'source_occurrences': None}
    index.write_filename_metadata(tmp_path, [clean], workers=1, previous=first)
    removed, = pq.read_table(path).to_pylist()
    assert removed['document_kind'] is removed['document_family'] is None
    assert removed['source_id'] == saved['source_id']
    assert removed['document_id'] == saved['document_id']


def test_document_aliases_share_family_without_promoting_one_alias_broad_fallback(tmp_path):
    (tmp_path/'indexes').mkdir()
    rows = [dict(filename=name, body_key='same-pdf', source_url=f'https://www.judiciary.senate.gov/download/{i}',
                 media_type=['application/pdf'], http_status=['200'], source_occurrences=[occurrence()])
            for i,name in enumerate(['Aramayo Support for de Alba.pdf', 'Aramayo Letter of Support for de Alba.pdf'])]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    path = tmp_path/'indexes/document-filenames.parquet'
    before = pq.read_table(path.with_name('documents.parquet'))
    document, = before.to_pylist()
    assert document['document_kind'] == ['letter-of-support']
    assert document['document_family'] == ['letter', 'nomination-support']
    index.reindex_documents(tmp_path)
    assert before.equals(pq.read_table(path.with_name('documents.parquet')))

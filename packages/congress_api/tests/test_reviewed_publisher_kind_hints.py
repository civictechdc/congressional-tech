"""Only attributable, agreeing publisher labels fill missing document kinds."""
import pytest
from congress_api.retention.document_index import fill_document_kind


def anchor(label,heading=None,**extra):
    return {'source_occurrence_scope':['anchor'],'source_association_basis':['retained_html_link'],
            'source_original_page_url':['https://transportation.house.gov/hearings/1'],
            'source_link_url':['https://transportation.house.gov/file.pdf'],
            'source_link_label':[label],'source_link_heading':[heading] if heading else [],**extra}


def apply(*occurrences,**extra):
    row={'record_role':['document'],'source_occurrences':list(occurrences),**extra}
    fill_document_kind(row)
    return row


@pytest.mark.parametrize('label,kind',[
    ('Written Testimony','testimony'),('Download the Witness Testimony','witness-statement'),
    ('Preliminary Transcript','transcript'),('Transcript [PDF]','transcript'),
    ('Summary of Subject Matter','committee-memorandum'),
    ('Subcommittee Hearing Notice','meeting-notice'),
    ('Truth in Testimony Form','testimony-disclosure'),
    ('Opening Statement','opening-statement'),('Amendment Text','amendment'),
    ('roll call vote','committee-vote'),('Hearing Charter','hearing-charter'),
    ('Updated: Subcommittee Hearing Notice','meeting-notice'),
    ('Official Hearing Notice','meeting-notice'),
    ('A preliminary transcript of this hearing is now available.','transcript'),
    ('A transcript of this hearing is now available.','transcript'),
    ('Amendment #12 to H.R. 2187 by Mr. Polis (CO) »','amendment'),
    ('Amendment 41 to H.R. 3200 by Mr. Price (GA)','amendment'),
])
def test_explicit_anchored_labels_fill_gaps(label,kind):
    row=apply(anchor(label))
    assert row['document_kind']==[kind]
    assert row['document_kind_source']==['source_context']


def test_explicit_disclosure_outranks_broad_testimony_section():
    assert apply(anchor('Truth in Testimony Form','Testimony'))['document_kind']==['testimony-disclosure']


def test_conflicting_and_unknown_anchor_claims_abstain():
    for other in ['Opening Statement','Download document']:
        assert not apply(anchor('Hearing Memo'),anchor(other)).get('document_kind')


def test_flat_union_and_unproven_associations_do_not_supply_kind():
    assert not apply(source_link_label=['Written Testimony']).get('document_kind')
    assert not apply(anchor('Written Testimony',source_association_basis=['user_accepted_url_variant'])).get('document_kind')
    assert not apply(anchor('Written Testimony',source_original_page_url=['https://example.org/page'])).get('document_kind')


def test_generic_and_topic_labels_abstain():
    for label in ['Document','PDF','XML','Agenda','The amendment was not agreed to by a roll call vote of 16 yeas to 24 nays.','Hearing about testimony requirements',
                  'Amendment #1 by Mr. Smith vote tally', 'Amendment #1 by Mr. Smith report',
                  'A hearing about preliminary transcript requirements.']:
        assert not apply(anchor(label)).get('document_kind')


def test_filename_and_typed_content_remain_authoritative():
    assert apply(anchor('Hearing Notice'),document_kind=['committee-memorandum'])['document_kind']==['committee-memorandum']
    assert apply(anchor('Hearing Notice'),content_document_kind=['committee-memorandum'])['document_kind']==['committee-memorandum']


def test_legacy_anchor_without_basis_requires_an_exact_known_source_link():
    legacy=anchor('Preliminary Transcript',source_association_basis=[])
    assert apply(legacy,source_url='https://transportation.house.gov/file.pdf')['document_kind']==['transcript']
    assert not apply(legacy,source_url='https://transportation.house.gov/other.pdf').get('document_kind')


def test_media_role_does_not_take_document_context():
    assert not apply(anchor('Opening Statement'),record_role=['media']).get('document_kind')


def test_index_writer_and_cached_source_refresh_use_new_hints(tmp_path):
    import pyarrow.parquet as pq
    from catalog_test_helpers import selected_path
    from congress_api.retention import document_index as index

    (tmp_path/'indexes').mkdir()
    source={'filename':'opaque-001.pdf','source_url':'https://transportation.house.gov/file.pdf',
            'body_key':None,'source_occurrences':[anchor('Written Testimony')]}
    index.write_filename_metadata(tmp_path,[source],workers=1)
    path=tmp_path/'indexes/document-filenames.parquet'
    previous=pq.read_table(selected_path(path))
    assert previous.to_pylist()[0]['document_kind']==['testimony']
    source['source_occurrences']=[anchor('Preliminary Transcript')]
    stats=index.write_filename_metadata(tmp_path,[source],workers=1,previous=previous)
    assert stats['parsed_inputs']==0
    for table in ['document-filenames.parquet','documents.parquet']:
        row,=pq.read_table(selected_path(tmp_path/'indexes'/table)).to_pylist()
        assert row['document_kind']==['transcript']
        assert row['document_kind_source']==['source_context']

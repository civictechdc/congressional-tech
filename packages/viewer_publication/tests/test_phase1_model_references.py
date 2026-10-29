"""Reference occurrences retain provenance without inventing acquisitions.

Exact maintained URL keys may attach a metadata occurrence to one held body.
The original occurrence keeps its receipt locator and null acquisition digest.
Reference dates never become fetch dates. Filename similarity and an address
holding different body editions leave the association unresolved.
"""
import json
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,list_of,run_job
from docspec_client.client import NativeDatasets


def test_native_references_preserve_occurrences_without_inventing_acquisitions(tmp_path):
    from viewer_publication.archive_model import ROOT,registry_inputs,source_steps
    fixture=json.loads((ROOT/'model/fixtures/reference-sources.json').read_text())
    held=fixture['url_digest_examples'][0]['item'][0]
    meeting=lambda number:f'https://docs.house.gov/meetings/AG/AG03/20261020/HMKP{number}/index.html'
    def row(line,url,*,outcome='stored',body='a'*64,context=None,day=20):
        return dict(receipt_key='receipts/documents/undated/assemble-model.jsonl.gz',
            receipt_line=line,capture_index=0,run_id='fixture',mode='fetch',outcome=outcome,
            url=url,requested_url=url,context_url=context or url,member_path=None,
            h_content_disposition=None,retrieved_at=f'2026-10-{day:02d}T12:00:00Z',
            body_hex=body,format='pdf' if body else None,is_real_file=body is not None,
            record_role='document' if body else None)
    rows=[row(1,held),
        row(2,held,outcome='reference',body=None,context=meeting(123),day=29),
        row(3,held.replace('http://docs.house.gov','https://www.docs.house.gov')+'?utm_source=mention#part',
            outcome='reference',body=None,context=meeting(456),day=19),
        row(4,held.replace('docs.house.gov','unrelated.test'),outcome='reference',body=None,
            context=meeting(999),day=29),
        row(5,'https://fixture.test/unknown.pdf',outcome='saved-record',body=None,day=29),
        row(6,'https://fixture.test/failed.pdf',outcome='failed',body=None,day=28),
        row(7,'https://fixture.test/edition.pdf',body='b'*64),
        row(8,'https://fixture.test/edition.pdf',body='c'*64),
        row(9,'https://fixture.test/edition.pdf',outcome='reference',body=None,
            context=meeting(888),day=29),
        row(10,held,outcome='saved-record',body=None,day=29)]
    # These literals come directly from the complete raw-shape census. Never repair them.
    for number,example in enumerate(fixture['malformed_references'],11):
        rows.append(dict(row(number,example['literal_url'],outcome='reference',body=None),
            receipt_key=example['receipt_key'],receipt_line=example['receipt_line'],
            capture_index=example['record_index']))
    malformed_lines={example['receipt_line'] for example in fixture['malformed_references']}
    inputs=registry_inputs(tmp_path/'registries')
    inputs += [json_input(tmp_path,'fixture_captures',rows,receipt_key='Utf8',receipt_line='Int32',
        capture_index='Int32',run_id='Utf8',mode='Utf8',outcome='Utf8',url='Utf8',requested_url='Utf8',
        context_url='Utf8',member_path='Utf8',h_content_disposition='Utf8',retrieved_at='Utf8',
        body_hex='Utf8',format='Utf8',is_real_file='Boolean',record_role='Utf8'),
        json_input(tmp_path,'current_recoveries',[],id='Utf8',original_url='Utf8',
            recovered_filename='Utf8',kind='Utf8'),
        json_input(tmp_path,'url_variants',[],canonical_url='Utf8',variant_url='Utf8'),
        json_input(tmp_path,'publisher_links',[],source_id='Utf8',context_url='Utf8'),
        json_input(tmp_path,'page_facts',[],body_sha='Binary',status='Utf8',named_meetings=list_of('Int64')),
        json_input(tmp_path,'resolved_links',[],target_url='Utf8')]
    steps=[dict(name='capture_evidence',sql="""SELECT * EXCLUDE(body_hex,is_real_file,record_role),
            decode(body_hex,'hex') AS sha256 FROM fixture_captures"""),
        dict(name='record_roles',sql='SELECT receipt_key,receipt_line,capture_index,is_real_file,record_role FROM fixture_captures')]
    steps += source_steps()
    steps += [dict(name='captures',sql='SELECT * FROM capture_evidence'),
        dict(name='good_fetches',sql='SELECT receipt_key,receipt_line,capture_index FROM fixture_captures WHERE is_real_file'),
        dict(name='source_addresses',sql=(ROOT/'model/sql/source-addresses.sql').read_text(),materialize=True),
        dict(name='url_inputs',sql=(ROOT/'model/sql/model-url-inputs.sql').read_text(),materialize=True),
        dict(name='url_normalized',sql=(ROOT/'model/sql/url-normalized.sql').read_text(),materialize=True),
        dict(name='model_url_keys',sql=(ROOT/'model/sql/url-keys.sql').read_text(),materialize=True),
        dict(name='source_endpoints',sql=(ROOT/'model/sql/source-endpoints.sql').read_text(),materialize=True)]
    for name in ('addresses','meetings'):
        steps.append(dict(name='source_annotation_'+name,
            sql=(ROOT/'model/sql'/('source-annotations-'+name+'.sql')).read_text(),materialize=True))
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs,steps=steps,outputs=[],queries=[
            dict(name='occurrences',sql="""SELECT receipt_key,receipt_line,capture_index,source_id,
                encode(sha256,'hex') AS acquisition_body,body_sha,context_url
                FROM capture_sources ORDER BY receipt_line"""),
            dict(name='files',sql="""SELECT source_id,body_sha,filename,source_url,
                cast(first_fetched AS VARCHAR) AS first_fetched,
                cast(last_fetched AS VARCHAR) AS last_fetched FROM source_files ORDER BY source_id"""),
            dict(name='meetings',sql='SELECT source_id,meeting_keys FROM source_annotation_meetings ORDER BY source_id'),
            dict(name='invalid_keys',sql='SELECT count(*) AS n FROM model_url_keys WHERE error IS NOT NULL'),
            dict(name='invented_endpoints',sql="SELECT count(*) AS n FROM source_endpoints WHERE endpoint_key LIKE '%HMKP%'")])
    occurrences={item['receipt_line']:item for item in result['occurrences']}
    assert set(occurrences)==set(range(1,11))|malformed_lines
    owned=occurrences[1]['source_id']
    for line,context in ((2,meeting(123)),(3,meeting(456))):
        mention=occurrences[line]
        assert mention['source_id']==owned and mention['body_sha']=='a'*64
        assert mention['acquisition_body'] is None and mention['context_url']==context
        assert mention['receipt_key']==rows[line-1]['receipt_key'] and mention['capture_index']==0
    for line in (4,5,9,10,*sorted(malformed_lines)):
        mention=occurrences[line]
        assert mention['source_id']!=owned and mention['body_sha'] is None
        assert mention['acquisition_body'] is None
    # Neither possible edition can acquire evidence from the ambiguous mention.
    assert occurrences[9]['source_id'] not in {occurrences[7]['source_id'],occurrences[8]['source_id']}
    files={item['source_id']:item for item in result['files']}
    assert files[owned]['first_fetched'].startswith('2026-10-20')
    assert files[owned]['last_fetched'].startswith('2026-10-20')
    for line in (4,5,9,10,*sorted(malformed_lines)):
        assert files[occurrences[line]['source_id']]['first_fetched'] is None
        assert files[occurrences[line]['source_id']]['last_fetched'] is None
    assert files[occurrences[6]['source_id']]['first_fetched'].startswith('2026-10-28')
    meetings={item['source_id']:item['meeting_keys'] for item in result['meetings']}
    assert meetings[owned]==['111183','123','456']
    assert '999' not in meetings[owned] and '888' not in meetings[owned]

    assert result['invalid_keys']==[dict(n=0)]
    assert result['invented_endpoints']==[dict(n=0)]

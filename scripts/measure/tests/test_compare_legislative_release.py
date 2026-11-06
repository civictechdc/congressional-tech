"""A planted in-domain value and an extra row must fail detail conservation."""
import importlib.util
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq


def test_source_comparison_detects_value_corruption_and_multiplicity(tmp_path):
    spec=importlib.util.spec_from_file_location('compare_legislative_release',Path(__file__).parents[1]/'compare_legislative_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source';source.mkdir();release=tmp_path/'release';release.mkdir()
    manifest=dict(generations={'bill-family':'a'*64,'roll-call-votes':'b'*64},tables={})
    for name,family,row in [('bill_actions','bill-family',dict(bill_id='119-hr-1',action_index=1,action_text='Passed')),
        ('roll_call_votes','roll-call-votes',dict(vote_id='v1',yea=60,nay=40)),
        ('member_votes','roll-call-votes',dict(vote_id='v1',member_key='lis:S1',bioguide_id=None))]:
        key=name+'.parquet';raw=pa.Table.from_pylist([row]);pq.write_table(raw,source/key)
        manifest['tables']['spicy_'+name]=dict(path=key)
        row.update(source_generation=manifest['generations'][family],source_reference=key)
        pq.write_table(pa.Table.from_pylist([row]),release/key)
    pin=source/'spicy-regs.json';pin.write_text(json.dumps(manifest))
    assert module.compare(pin,release,tmp_path/'work')['match']
    path=release/'bill_actions.parquet';rows=pq.read_table(path).to_pylist();rows[0]['action_text']='Failed';pq.write_table(pa.Table.from_pylist(rows),path)
    bad=module.compare(pin,release,tmp_path/'work')
    assert not bad['match'] and bad['relations']['bill_actions']['missing_rows']==bad['relations']['bill_actions']['added_rows']==1
    path=release/'member_votes.parquet';table=pq.read_table(path);pq.write_table(pa.concat_tables([table,table]),path)
    extra=module.compare(pin,release,tmp_path/'work')['relations']['member_votes']
    assert extra['missing_rows']==0 and extra['added_rows']==1

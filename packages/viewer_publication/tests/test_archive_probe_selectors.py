"""A valid metadata-first release still probes a visible saved document."""
import os

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


def test_native_probe_selection_skips_metadata_only_and_hidden_rows(tmp_path):
    from viewer_publication.archive_model import probe_selectors_query
    inputs=[json_input(tmp_path,'rows',[
        dict(list_row=0,body_hex=None,link_hex=None,hidden=False),
        dict(list_row=1,body_hex='a'*64,link_hex='a'*16,hidden=True),
        dict(list_row=2,body_hex='b'*64,link_hex='b'*16,hidden=False),
        dict(list_row=3,body_hex='c'*64,link_hex='c'*16,hidden=False)],
        list_row='Int32',body_hex='Utf8',link_hex='Utf8',hidden='Boolean')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='details',sql="SELECT list_row,hidden,decode(body_hex,'hex') AS saved_body,decode(link_hex,'hex') AS link_key FROM rows")],
        outputs=[],queries=[probe_selectors_query()])
    assert result['probe_selectors']==[dict(saved_row=2,link_key='b'*16)]

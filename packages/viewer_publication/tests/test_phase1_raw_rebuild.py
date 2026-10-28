"""Retained raw inputs reproduce the model, including after a policy change."""
import json
import os
from pathlib import Path
import shutil

from archive_job_fixture import real_model_spec,rebuild_model_spec
from docspec_client.client import NativeDatasets


def test_raw_only_rebuild_matches_before_and_after_registry_change(tmp_path):
    from viewer_publication.archive_model import build_release
    from viewer_publication.archive_model_profile import ROOT,_definition_hashes
    original=tmp_path/'original';original.mkdir()
    first,_,_=real_model_spec(original)
    reconstructed=tmp_path/'reconstructed';reconstructed.mkdir()
    second=rebuild_model_spec(reconstructed,raw=original/'raw',qualification=original/'receipt-pin.json')
    # The second producers receive raw and its qualification only. Every derived
    # input path is newly created; no old catalog, prior reading or filename row
    # is provided to the work-list anti-joins.
    for name in ['captures','readings','filename_readings']:
        assert first[name]['path']!=second[name]['path']
        assert Path(second[name]['path']).is_relative_to(reconstructed)
    changed=tmp_path/'changed-policy'
    for relative in _definition_hashes(ROOT):
        target=changed/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    policy=changed/'model/registries/capture-scope.json'
    value=json.loads(policy.read_text())
    next(row for row in value['entries'] if row['family']=='documents')['patterns'].append(r'^https://fixture\.test/')
    policy.write_text(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
    def build(spec,label,root):
        return build_release(**{name:spec[name]['path'] for name in ['captures','readings','filename_readings']},
            parser_versions=spec['parser_versions'],catalog_version=spec['catalog_version'],
            engine=engine,output=tmp_path/(label+'-release'),scratch=tmp_path/(label+'-model'),root=root)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        prior=build(first,'first',ROOT);rebuilt=build(second,'rebuilt',ROOT)
        updated=build(first,'updated',changed);updated_rebuilt=build(second,'updated-rebuilt',changed)
    assert prior==rebuilt and updated==updated_rebuilt
    assert prior['release_id']!=updated['release_id']
    for left,right,manifest in [('first','rebuilt',prior),('updated','updated-rebuilt',updated)]:
        for entry in manifest['files']:
            assert (tmp_path/(left+'-release')/entry['name']).read_bytes()==(tmp_path/(right+'-release')/entry['name']).read_bytes()

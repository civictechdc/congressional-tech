"""A seed identifies its approved catalog files without claiming raw lake inputs."""
from copy import deepcopy

import pytest


def arguments():
    return dict(catalog_id='4'*32,generation='5'*32,document_rows=1241157,
        input_files={name:dict(sha256=str(i)*64,size=i*100)
            for i,name in enumerate(['documents','filenames','captures','accepted'],1)},
        engine_revision='a'*40,definition_hashes={'model/sql/seed-v5.sql':'b'*64})


def test_seed_profile_names_all_sources_and_cannot_claim_capture_authority():
    from viewer_publication.archive_seed_profile import seed_profile_record,validate_seed_profile
    value=arguments();record=seed_profile_record(**value);profile=record['profile']
    assert profile['kind']=='seed_v5' and profile['display_only'] is True
    assert profile['label']=='seed: v5 catalog '+value['generation'][:8]
    assert profile['input_files']==value['input_files'] and profile['document_rows']==1241157
    assert record['snapshots']=={} and len(record['profile_sha256'])==64
    assert validate_seed_profile(profile)==profile
    value['input_files']['documents']['sha256']='c'*64
    assert profile['input_files']['documents']['sha256']=='1'*64


def test_seed_identity_changes_with_source_or_definition_but_not_dictionary_order():
    from viewer_publication.archive_seed_profile import seed_profile_record
    from viewer_publication.archive_publish import input_digest
    def digest(value):return input_digest(receipt_keys=[],provenance=[],entity_digests={},profile=seed_profile_record(**value)['profile'])
    value=arguments();first=digest(value)
    reordered=deepcopy(value);reordered['input_files']=dict(reversed(list(value['input_files'].items())))
    assert digest(reordered)==first
    changed=deepcopy(value);changed['input_files']['captures']['sha256']='c'*64
    assert digest(changed)!=first
    changed=deepcopy(value);changed['definition_hashes']['model/sql/seed-v5.sql']='d'*64
    assert digest(changed)!=first


@pytest.mark.parametrize('change',['missing_source','extra_source','bad_sha','bad_size','bad_rows',
                                  'bad_catalog','bad_generation','bad_engine','no_definitions'])
def test_seed_profile_requires_explicit_valid_input_identity(change):
    from viewer_publication.archive_seed_profile import seed_profile_record
    value=arguments()
    if change=='missing_source':del value['input_files']['accepted']
    elif change=='extra_source':value['input_files']['readings']=dict(sha256='a'*64,size=1)
    elif change=='bad_sha':value['input_files']['documents']['sha256']='bad'
    elif change=='bad_size':value['input_files']['documents']['size']=True
    elif change=='bad_rows':value['document_rows']=True
    elif change=='bad_catalog':value['catalog_id']='old'
    elif change=='bad_generation':value['generation']='old'
    elif change=='bad_engine':value['engine_revision']='old'
    else:value['definition_hashes']={}
    with pytest.raises(ValueError):seed_profile_record(**value)


@pytest.mark.parametrize('change',['capture_enabled','raw_kind','extra','bad_label','unsafe_definition'])
def test_recorded_seed_profile_is_validated_without_current_source_files(change):
    from viewer_publication.archive_seed_profile import seed_profile_record,validate_seed_profile
    profile=seed_profile_record(**arguments())['profile']
    if change=='capture_enabled':profile['display_only']=False
    elif change=='raw_kind':profile['kind']='model'
    elif change=='extra':profile['snapshots']={'captures':{}}
    elif change=='bad_label':profile['label']='rebuilt from raw'
    else:profile['definition_hashes']={'../unowned.sql':'b'*64}
    with pytest.raises(ValueError):validate_seed_profile(profile)

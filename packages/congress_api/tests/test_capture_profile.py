"""Capture policy comes from the same immutable release as its URL state."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from congress_api.archive_profile import build_capture_profile, validate_capture_profile

ROOT=Path(__file__).parents[3]
REVISION='a'*40


def profile():
    return build_capture_profile(engine_revision=REVISION,
        url_normalized_sql=(ROOT/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(ROOT/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((ROOT/'model/registries/url-rules.json').read_text()))


def test_public_profile_contains_the_exact_shared_definition_and_active_variant_file():
    value=profile()
    assert value['version']==1 and value['engine_revision']==REVISION
    assert value['url_variants_file']=='url_variants.parquet'
    assert set(value['sql'])=={'url_normalized','url_keys'}
    assert value['sql']['url_keys']['text']==(ROOT/'model/sql/url-keys.sql').read_text()
    assert all(set(rule)=={'id','kind','host_pattern','pattern','replacement','decoder'}
               for rule in value['url_rules'])
    assert validate_capture_profile(value,engine_revision=REVISION)==value


@pytest.mark.parametrize('change', ['engine','sql','path','version','version_bool',
                                   'duplicate_rule','kind_list','decoder_list','missing_replacement'])
def test_changed_or_incompatible_profile_refuses_before_capture(change):
    value=deepcopy(profile())
    if change=='engine':value['engine_revision']='b'*40
    elif change=='sql':value['sql']['url_keys']['text']+=' --changed'
    elif change=='path':value['url_variants_file']='../mutable.parquet'
    elif change=='version':value['version']=2
    elif change=='version_bool':value['version']=True
    elif change=='kind_list':value['url_rules'][0]['kind']=[]
    elif change=='decoder_list':value['url_rules'][0]['decoder']=[]
    elif change=='missing_replacement':value['url_rules'][0]['replacement']=None
    else:value['url_rules'].append(value['url_rules'][0])
    with pytest.raises(ValueError):
        validate_capture_profile(value,engine_revision=REVISION)

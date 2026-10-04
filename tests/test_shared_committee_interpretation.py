"""Committee source interpretation is usable without normalized record adapters."""

from copy import deepcopy

import pytest

from congress_api.matching import committees


def test_source_keys_preserve_congress_and_native_joint_identity():
    row = {'congress': '106', 'committee_code': ' SP2K00 ',
           'committee_codes': 'sp2k00;ssap00;invalid'}
    before = deepcopy(row)
    assert committees.source_committee_keys(row) == ((106, 'sp2k00'), (106, 'ssap00'))
    assert row == before
    assert committees.hierarchy_from_code('sp2k00') == ('full', None)
    assert committees.hierarchy_from_code('hsap18') == ('subcommittee', 'hsap00')
    assert committees.native_parent('hlvc01') == 'hlvc00'
    assert committees.parent_code('hlvc01') == 'hsgo00'


@pytest.mark.parametrize('row', [
    {'congress': True, 'committee_code': 'hsap00'},
    {'congress': 0, 'committee_code': 'hsap00'},
    {'congress': 'bad', 'committee_code': 'hsap00'},
    {'congress': 119, 'committee_code': 'unknown'},
])
def test_invalid_source_identity_stays_unknown(row):
    assert committees.source_committee_key(row) is None


def test_reviewed_overlay_preserves_native_input_and_explicit_scope():
    from congress_api.matching.committee_adjustments import ADJUSTMENTS, reviewed_adjustments

    source = {(106, 'jcfm00'): {'committeeTypeCode': 'Other'},
              (107, 'jcfm00'): {'committeeTypeCode': 'Other'},
              (119, 'scnc00'): {'committeeTypeCode': 'Other'}}
    before = deepcopy(source)
    decisions_before = deepcopy(ADJUSTMENTS)
    selected = {(congress, decision['code']): decision
                for congress, decision in reviewed_adjustments(source)}
    assert set(selected) == {(106, 'jcfm00'), (119, 'scnc00'),
                             (119, 'hshf00'), (119, 'sowg00')}
    assert selected[106, 'jcfm00']['values']['committee_type'] == 'commission_or_caucus'
    assert selected[119, 'scnc00']['evidence'][0]['url'].startswith('https://')
    assert list(reviewed_adjustments(source, congresses={115})) == []
    assert list(reviewed_adjustments({}, congresses={120})) == []
    additions = list(reviewed_adjustments({}, congresses={119}))
    assert {decision['code'] for _, decision in additions} == {'hshf00', 'sowg00'}
    selected[106, 'jcfm00']['values']['committee_type'] = 'consumer-local'
    assert ADJUSTMENTS == decisions_before
    assert source == before


def test_adapter_helpers_keep_the_existing_import_surface():
    from congress_api.adapters.committees import hierarchy_from_code, source_committee_keys

    assert hierarchy_from_code is committees.hierarchy_from_code
    assert source_committee_keys is committees.source_committee_keys

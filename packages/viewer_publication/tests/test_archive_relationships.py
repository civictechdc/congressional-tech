"""Independent declaration cases for the archive's explicitly selected rules."""
from hashlib import sha256
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[3]
PREFIX = 'urn:congressional-tech:archive:'


def key(kind, path=('key',)):
    from ddk.catalog_semantics import ResolvedKey

    definition = {'logicalType': 'string', 'physicalType': kind}
    shared = 'string'
    if kind.startswith('fixed['):
        definition['logicalTypeOptions'] = {'format': 'binary'}
        shared = None
    elif kind in {'int32', 'int64'}:
        definition['logicalType'] = 'integer'
        shared = 'integer'
    return ResolvedKey(tuple({'each': True} if segment == '[]' else {'field': segment}
                             for segment in path), definition, shared)


def relationship(rule, source, target, *, external=None, version='1.0.0', nulls='skip', scope='same_release'):
    from ddk.catalog_semantics import ResolvedRelationship

    declaration = {
        'id': PREFIX + 'relationship:independent-test',
        'source': {'dataset': 'documents'},
        'target': {'external': PREFIX + 'external:' + external} if external else {'dataset': 'documents'},
        'scope': 'external' if external else scope,
        'resolution': 'external' if external else 'required',
        'match': 'equal' if rule is None else 'project_rule', 'nulls': nulls,
    }
    if rule is not None:
        declaration['rule'] = {'id': PREFIX + 'match:' + rule, 'version': version}
    return ResolvedRelationship(declaration, tuple(source), None if external else tuple(target))


def assess(value):
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    return ArchiveRelationshipProfileV1().assess(value)


def test_public_binary_key_equality_requires_the_exact_width():
    assert assess(relationship(None, [key('fixed[8]')], [key('fixed[8]')])).status == 'supported'
    assert assess(relationship(None, [key('fixed[32]')], [key('fixed[8]')])).status == 'failed'
    assert assess(relationship(None, [key('string')], [key('fixed[8]')])).status == 'failed'
    assert assess(relationship(None, [key('fixed[16]')], [key('fixed[8]')])).status == 'unknown'


def test_virtual_row_positions_are_integers_within_one_release_only():
    from ddk.catalog_semantics import ResolvedKey

    position = ResolvedKey(({'field': 'list_row'},),
                           {'physicalType': 'int64', 'logicalType': 'int64'}, None, 'release')
    for source in (position, key('int32'), key('int64')):
        assert assess(relationship(None, [source], [position])).status == 'supported'
    assert assess(relationship(None, [key('string')], [position])).status == 'failed'
    across_releases = relationship(None, [key('int32')], [position], scope='cross_release')
    assert assess(across_releases).status == 'failed'
    other_scope = ResolvedKey(position.path, position.definition, None, 'dataset_version')
    assert assess(relationship(None, [key('int32')], [other_scope])).status == 'unknown'
    other_position = ResolvedKey(({'field': 'other_row'},), position.definition, None, 'release')
    assert assess(relationship(None, [key('int32')], [other_position])).status == 'unknown'


def test_decimal_and_edition_rules_check_their_distinct_key_meaning():
    assert assess(relationship('decimal_string_to_integer', [key('dict')], [key('int64')])).status == 'supported'
    assert assess(relationship('decimal_string_to_integer', [key('string')], [key('string')])).status == 'failed'
    editions = relationship('shared_list_value', [key('dict', ('versions', '[]'))],
                            [key('dict', ('versions', '[]'))])
    assert assess(editions).status == 'supported'
    assert assess(relationship('shared_list_value', [key('string')], [key('string')])).status == 'failed'


@pytest.mark.parametrize('rule,version', [('future_rule', '1.0.0'), ('identifier', '2.0.0')])
def test_unrecognized_rule_or_version_remains_unknown(rule, version):
    value = relationship(rule, [key('string')], None, external='2aa617eebe482411', version=version)
    assert assess(value).status == 'unknown'


def test_external_identifiers_keep_namespace_and_availability_separate():
    package = relationship('identifier', [key('string')], None, external='2aa617eebe482411')
    result = assess(package)
    assert result.status == 'supported'
    assert assess(relationship('identifier', [key('string')], None, external='not-a-known-namespace')).status == 'unknown'
    assert assess(relationship('identifier', [key('int64')], None, external='2aa617eebe482411')).status == 'failed'
    assert assess(relationship('identifier', [key('string')], [key('string')])).status == 'failed'


def test_body_path_uses_digest_then_suffix_from_the_same_object():
    digest = key('fixed[32]', ('alternates', '[]', 'body'))
    suffix = key('dict', ('alternates', '[]', 'suffix'))
    make = lambda parts: relationship('identifier', parts, None, external='4e3f0ee3f6f0f2f4')
    assert assess(make([digest, suffix])).status == 'supported'
    assert assess(make([suffix, digest])).status == 'failed'
    assert assess(make([digest, key('dict', ('other', '[]', 'suffix'))])).status == 'failed'
    assert assess(make([key('fixed[8]', ('alternates', '[]', 'body')), suffix])).status == 'failed'


def test_unknown_null_matching_is_not_promoted():
    assert assess(relationship(None, [key('fixed[8]')], [key('fixed[8]')], nulls='unknown')).status == 'unknown'


def test_real_catalog_uses_selected_profile_without_claiming_observed_data():
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    profile = ArchiveRelationshipProfileV1()
    result = assemble_catalog(ROOT / 'model/ddk/project.ddk.json',
                              permitted_roots=[ROOT], relationship_profile=profile)
    assert result.report['decision'] == 'passed', result.local_report
    checks = [item for item in result.report['checks'] if item['group'] == 'catalog.relationships']
    assert len(checks) == 70 and all(item['status'] == 'passed' for item in checks)
    assessments = result.local_report['metadata']['relationshipAssessments']
    assert len(assessments) == 38
    assert all(item['scope'] == 'declaration-support-only' for item in assessments)
    external = [item for item in assessments if 'externalExistence' in item]
    assert len(external) == 28 and all(item['externalExistence'] == 'not_assessed' for item in external)
    for field in ('versions', 'releases', 'selections', 'runs'):
        assert result.catalog[field] == []
    # The exact selected implementation is retained as input provenance.
    digest = sha256(profile.source.read_bytes()).hexdigest()
    assert digest in json.dumps(result.local_report)


def test_shared_admission_still_refuses_a_missing_key_before_profile_success(tmp_path):
    import shutil
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    shutil.copytree(ROOT / 'model/ddk', tmp_path / 'definitions')
    path = tmp_path / 'definitions/project.ddk.json'
    project = json.loads(path.read_text())
    relation = next(row for row in project['catalog']['relationships']
                    if row['id'].endswith(':document_meetings'))
    relation['source']['paths'] = [[{'field': 'absent_meeting_key'}]]
    path.write_text(json.dumps(project))
    result = assemble_catalog(path, permitted_roots=[tmp_path, ROOT],
                              relationship_profile=ArchiveRelationshipProfileV1())
    assert result.report['decision'] == 'failed'
    assert not result.artifacts

"""Declared archive comparison semantics for DDK's selected relationship profile.

This module checks declarations only. Native qualification must separately
establish actual matches, cardinality and reference completeness; external
availability stays unobserved.
"""
from pathlib import Path

from ddk.catalog_semantics import RelationshipAssessment, ResolvedRelationship


NAMESPACE = 'urn:congressional-tech:archive:'

# Exact external namespace identities are authored in the archive project. Each
# entry specifies how its ordered key is interpreted, without contacting it or
# asserting that any target exists. Opaque identifiers retain their source bytes.
EXTERNAL_KEYS = {
    '95bc9c9d99202062': (('string',), 'Literal SpicyRegs roll-call vote identifier.'),
    'ee02b90bbc1969f1': (('string',), 'Literal Senate LIS identifier.'),
    '3860bd237aa59e1e': (('string',), 'Literal OpenSecrets identifier.'),
    'ce89e33957f7bf63': (('string',), 'Literal GovTrack identifier; no numeric coercion.'),
    '2bcd5c8ae9818dd0': (('string',), 'Literal ICPSR identifier; no numeric coercion.'),
    'a8269b6531320c99': (('string',), 'Literal Wikidata identifier.'),
    '7a04676ecd7228d8': (('string',), 'One literal FEC identifier per list element.'),
    '7fb151823cb39078': (('string',), 'Literal CBO publication identifier.'),
    'e43e10f2c1946f49': (('string',), 'Literal SpicyRegs amendment identifier.'),
    '2aa617eebe482411': (('string',), 'Literal GovInfo package identifier.'),
    'fd1d05c5a9e82882': (('string',), 'Literal source URL; no lookup-key normalization or local-document claim.'),
    'fa8d1cf926ba824d': (('string',), 'Only {congress}-treaty-{number} values identify treaties; other subject kinds are outside this relationship.'),
    '4e3f0ee3f6f0f2f4': (('fixed[32]', 'string'),
        'Lowercase hexadecimal SHA-256 plus the literal saved suffix: bodies/sha256/{first two hex characters}/{full hex digest}{suffix}.'),
}


def _kind(key):
    definition = key.definition
    physical = definition.get('physicalType')
    if (definition.get('logicalType') == 'string'
            and definition.get('logicalTypeOptions', {}).get('format') == 'binary'
            and physical in {'fixed[8]', 'fixed[32]'}):
        return physical
    if key.shared_type == 'string' and physical in {'string', 'dict'}:
        return 'string'
    if key.shared_type == 'integer' and physical in {'int32', 'int64'}:
        return 'integer'
    return None


def _types(actual, expected, reason):
    if any(kind is None for kind in actual):
        return RelationshipAssessment('unknown', 'This profile does not interpret a supplied physical key type.')
    if actual != expected:
        return RelationshipAssessment('failed', 'Ordered key types do not implement the declared archive rule.')
    return RelationshipAssessment('supported', reason)


def _row_positions(relationship):
    """Interpret the archive's virtual row offset within one exact release."""
    if relationship.declaration['scope'] != 'same_release':
        return RelationshipAssessment('failed', 'A virtual row position only identifies a row within the same release.')
    if len(relationship.source) != 1 or len(relationship.target) != 1:
        return RelationshipAssessment('unknown', 'Archive row-position equality uses one integer on each side.')
    for key in (*relationship.source, *relationship.target):
        if key.virtual_scope is not None:
            if (key.virtual_scope != 'release' or key.path != ({'field': 'list_row'},)
                    or key.definition.get('physicalType') != 'int64'):
                return RelationshipAssessment('unknown', 'Only the declared release-local list_row position is supported.')
        elif _kind(key) != 'integer':
            return RelationshipAssessment('unknown' if _kind(key) is None else 'failed',
                                          'A physical reference to list_row must be an integer.')
    return RelationshipAssessment('supported',
        'Equal zero-based integer row positions within one release, including declared shard offsets; '
        'positions are not identifiers across releases. Native checks establish actual bounds and correspondence.')


class ArchiveRelationshipProfileV1:
    """Explicitly selected archive rules; no registry loading or row evaluation."""

    identity = {'id': NAMESPACE + 'relationship-profile', 'version': '1.0.0'}
    source = Path(__file__)

    def assess(self, relationship: ResolvedRelationship) -> RelationshipAssessment:
        declaration = relationship.declaration
        source = tuple(_kind(key) for key in relationship.source)
        target = None if relationship.target is None else tuple(_kind(key) for key in relationship.target)

        if declaration['nulls'] not in {'skip', 'reject'}:
            return RelationshipAssessment('unknown', 'This profile does not define a match between null keys.')
        if declaration['match'] == 'equal':
            if target is None:
                return RelationshipAssessment('unknown', 'External identifiers require their explicit archive construction rule.')
            if any(key.virtual_scope is not None for key in (*relationship.source, *relationship.target)):
                return _row_positions(relationship)
            if len(source) != 1 or len(target) != 1 or 'fixed[8]' not in source + target:
                return RelationshipAssessment('unknown', 'This profile qualifies fixed[8] public-key equality only.')
            return _types(source + target, ('fixed[8]', 'fixed[8]'),
                          'Exact equality of eight binary bytes; hexadecimal display spelling is not the key.')

        rule = declaration.get('rule', {})
        if declaration['match'] != 'project_rule' or rule.get('version') != '1.0.0':
            return RelationshipAssessment('unknown', 'The exact archive comparison rule version is unsupported.')
        identifier = rule.get('id')
        if identifier not in {NAMESPACE + 'match:' + name for name in
                              ('identifier', 'decimal_string_to_integer', 'shared_list_value')}:
            return RelationshipAssessment('unknown', 'This exact archive comparison rule identifier is unsupported.')
        if identifier == NAMESPACE + 'match:identifier':
            if target is not None or declaration['scope'] != 'external' or declaration['resolution'] != 'external':
                return RelationshipAssessment('failed', 'An external identifier cannot claim local target resolution.')
            external = declaration['target']['external']
            prefix = NAMESPACE + 'external:'
            semantics = EXTERNAL_KEYS.get(external[len(prefix):]) if external.startswith(prefix) else None
            if semantics is None:
                return RelationshipAssessment('unknown', 'This exact external namespace has no supported archive construction rule.')
            expected, reason = semantics
            if expected == ('fixed[32]', 'string') and len(relationship.source) == 2:
                left, right = relationship.source
                if left.path[:-1] != right.path[:-1]:
                    return RelationshipAssessment('failed', 'The body digest and suffix must belong to the same object or list element.')
            return _types(source, expected, reason + ' Target existence is not assessed.')

        if target is None or declaration['scope'] != 'same_release':
            return RelationshipAssessment('failed', 'This archive comparison requires both datasets in the same release.')
        if identifier == NAMESPACE + 'match:decimal_string_to_integer':
            return _types(source + target, ('string', 'integer'),
                          'Decimal-text meeting key compared with the integer event identifier; native rules check conversion and resolution.')
        if identifier == NAMESPACE + 'match:shared_list_value':
            if (declaration['source']['dataset'] != declaration['target']['dataset']
                    or any(not any(segment.get('each') is True for segment in key.path)
                           for key in (*relationship.source, *relationship.target))):
                return RelationshipAssessment('failed', 'Edition matching requires list elements on both sides of the same dataset.')
            return _types(source + target, ('string', 'string'),
                          'Rows share a literal version-list value; exclude the same row and return each other row once.')

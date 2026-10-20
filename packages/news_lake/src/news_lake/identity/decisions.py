"""The identity decision-graph owner (C6) — the part the docs checker skipped.

apply_decisions(records) resolves entity roots by replaying the
identity_decision records found in the record set. Validation and application
are one pure, replayable pass:

- Decisions are ordered by (recorded_at, id); retractions are excluded from
  application and un-apply exactly their target (application is recomputed
  from the surviving decisions, so removal only ever relaxes constraints).
- same_as(left, right) maps left to right (directional): the left group's
  root is attached to the right group's root, so chains are transitive.
- A same_as whose literal arrow (left -> right) would close a directed cycle
  is rejected; a same_as between already-equivalent entities is a benign
  confirmation, but its arrow is still recorded so later reachability checks
  see the decisions that were actually applied.
- A reflexive same_as/different_from (left == right) is rejected as
  reflexive_identity_decision before any cycle or contradiction check.
- different_from(left, right) prohibits equivalence: a later same_as across
  the pair (or across their groups) is rejected, and a different_from between
  equivalent entities is rejected.
- Merging two entities whose identifiers collide on one scheme with different
  values is an authoritative-ID conflict and fails.
- A retraction must name an earlier (by the same ordering) non-retraction
  decision that is currently applied.
"""
from news_lake.context import parse_instant
from news_lake.contract.errors import ContractError


def _decision_order(decision):
    return (parse_instant(decision['recorded_at']), decision['id'])


class _Graph:
    """Literal decision arrows and equivalence classes are separate structures.

    ``edges`` records exactly the active same_as arrows (left -> right); it
    drives reachability/cycle checks and identifies a class's unique
    downstream sink. ``parent`` is a Union-Find forest for equivalence-class
    membership; union-find roots are never written into the literal edge set.
    ``follow`` resolves a class to its root, using that unique sink when the
    arrows identify one unambiguously.
    """

    def __init__(self, entities):
        self.entities = entities  # entity id -> entity record (identifiers)
        self.edges = {}           # literal arrow: node -> set(nodes)
        self.parent = {}          # Union-Find: node -> parent
        self.distinct_pairs = []  # different_from endpoint pairs (original ids)
        self.known = set(entities)
        self._roots = None        # cache: node -> resolved class root

    # -- resolution -------------------------------------------------------------

    def _uf_root(self, node):
        while node in self.parent:
            node = self.parent[node]
        return node

    def _resolved_roots(self):
        if self._roots is None:
            classes = {}
            for node in self.known:
                classes.setdefault(self._uf_root(node), set()).add(node)
            roots = {}
            for union_root, members in classes.items():
                sinks = [
                    member for member in members
                    if not (self.edges.get(member, set()) & members)
                ]
                # A single sink is the unambiguous downstream identity. With
                # several consistent outgoing branches, keep the directional
                # union root as the deterministic tie-break.
                root = sinks[0] if len(sinks) == 1 else union_root
                for member in members:
                    roots[member] = root
            self._roots = roots
        return self._roots

    def follow(self, node):
        return self._resolved_roots().get(node, node)

    def reaches(self, start, target):
        """True iff start == target or a literal left->right path exists."""
        if start == target:
            return True
        seen = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for successor in self.edges.get(node, ()):
                if successor == target:
                    return True
                if successor not in seen:
                    stack.append(successor)
        return False

    def group(self, node):
        root = self.follow(node)
        return sorted(member for member in self.known if self.follow(member) == root)

    # -- application ------------------------------------------------------------

    def merge(self, left, right, decision):
        if left == right:
            raise ContractError(
                'reflexive_identity_decision',
                f'same_as({left}, {right}) relates an entity to itself',
                record_id=decision['id'],
            )
        self.known.update((left, right))
        if self.reaches(right, left):
            raise ContractError(
                'decision_cycle',
                f'same_as({left}, {right}) closes a directed cycle',
                record_id=decision['id'],
            )
        root_left, root_right = self._uf_root(left), self._uf_root(right)
        if root_left != root_right:
            self._check_distinct(left, right, decision)
            self._check_identifiers(left, right, decision)
            self.parent[root_left] = root_right
            self._roots = None
        # Record the literal arrow even for a confirmation: it is what was
        # decided, and later reachability checks must see it.
        self.edges.setdefault(left, set()).add(right)
        self._roots = None

    def differentiate(self, left, right, decision):
        if left == right:
            raise ContractError(
                'reflexive_identity_decision',
                f'different_from({left}, {right}) relates an entity to itself',
                record_id=decision['id'],
            )
        self.known.update((left, right))
        self._roots = None
        if self._uf_root(left) == self._uf_root(right):
            raise ContractError(
                'contradictory_decision',
                f'different_from({left}, {right}) asserts distinction over equivalent entities',
                record_id=decision['id'],
            )
        pair = (left, right) if left < right else (right, left)
        if pair not in self.distinct_pairs:
            self.distinct_pairs.append(pair)

    def _check_distinct(self, left, right, decision):
        merging = {self.follow(left), self.follow(right)}
        for a, b in self.distinct_pairs:
            if {self.follow(a), self.follow(b)} == merging and self.follow(a) != self.follow(b):
                raise ContractError(
                    'contradictory_decision',
                    f'same_as({left}, {right}) would equate the different_from pair ({a}, {b})',
                    record_id=decision['id'],
                )

    def _check_identifiers(self, left, right, decision):
        by_scheme = {}
        for entity_id in self.group(left) + self.group(right):
            entity = self.entities.get(entity_id)
            if entity is None:
                continue
            for identifier in entity.get('identifiers', []):
                by_scheme.setdefault(identifier['scheme'], set()).add(identifier['value'])
        colliding = sorted(scheme for scheme, values in by_scheme.items() if len(values) > 1)
        if colliding:
            raise ContractError(
                'authoritative_id_conflict',
                f'merging would collide identifier schemes {colliding} with different values',
                record_id=decision['id'],
            )


def apply_decisions(records):
    """Resolve entity roots from a record set; pure and replayable.

    Returns {'roots': {entity_id: root_id}, 'groups': {root_id: [entity_ids]},
    'applied': [decision ids], 'retracted': [decision ids]}. Every entity in
    the record set and every decision endpoint appears in roots; an entity
    with no surviving merge maps to itself.
    """
    entities = {record['id']: record for record in records if record.get('kind') == 'entity'}
    decisions = sorted(
        (record for record in records if record.get('kind') == 'identity_decision'),
        key=_decision_order,
    )
    order_index = {decision['id']: index for index, decision in enumerate(decisions)}
    by_id = {decision['id']: decision for decision in decisions}

    applied = []  # currently-active decisions, in application order
    retracted = set()
    for decision in decisions:
        if decision['action'] == 'retract':
            target_id = decision['prior_decision_id']
            target = by_id.get(target_id)
            if target is None:
                raise ContractError(
                    'retraction_target_missing',
                    f'retraction names unknown decision {target_id}',
                    record_id=decision['id'],
                )
            if target['action'] == 'retract':
                raise ContractError(
                    'retraction_target_retraction',
                    'a retraction must target a non-retraction decision',
                    record_id=decision['id'],
                )
            if order_index[target_id] >= order_index[decision['id']]:
                raise ContractError(
                    'retraction_target_not_earlier',
                    'a retraction must target an earlier decision (recorded_at, id order)',
                    record_id=decision['id'],
                )
            if target_id in retracted:
                raise ContractError(
                    'retraction_target_already_retracted',
                    f'decision {target_id} is already un-applied',
                    record_id=decision['id'],
                )
            applied = [d for d in applied if d['id'] != target_id]
            retracted.add(target_id)
            continue
        applied.append(decision)

    graph = _Graph(entities)
    for decision in applied:
        left, right = decision['left_id'], decision['right_id']
        if decision['action'] == 'same_as':
            graph.merge(left, right, decision)
        else:
            graph.differentiate(left, right, decision)

    every_id = set(entities)
    for decision in decisions:
        for field in ('left_id', 'right_id'):
            if field in decision:
                every_id.add(decision[field])
    roots = {entity_id: graph.follow(entity_id) for entity_id in sorted(every_id)}
    groups = {}
    for entity_id, root in roots.items():
        groups.setdefault(root, []).append(entity_id)
    return {
        'roots': roots,
        'groups': {root: sorted(members) for root, members in groups.items()},
        'applied': [decision['id'] for decision in applied],
        'retracted': sorted(retracted),
    }

"""Traversal over the catalog's existing relationship records."""
from __future__ import annotations

from collections import deque
from typing import Literal

from .common import Ref


class CatalogGraph:
    """Index MaterialLink, material relations, meetings, and appearances.

    MaterialLink is the association. Id tuples on Material are not a second one.
    """

    def __init__(self, catalog):
        self.catalog = catalog
        self._by_ref: dict[tuple[str, str], object] = {}
        self._outgoing: dict[tuple[str, str], list[tuple[str, Ref, object]]] = {}
        self._incoming: dict[tuple[str, str], list[tuple[str, Ref, object]]] = {}

        for src in catalog.sources:
            self._by_ref[(src.kind, src.id)] = src
        for rec in catalog.records:
            self._by_ref[(rec.kind, rec.id)] = rec

        for rec in catalog.records:
            self._index_record(rec)

    def _add_edge(self, source: Ref, target: Ref, relation: str, carrier: object):
        s_key = (source.kind, source.id)
        t_key = (target.kind, target.id)
        self._outgoing.setdefault(s_key, []).append((relation, target, carrier))
        self._incoming.setdefault(t_key, []).append((relation, source, carrier))

    def _index_record(self, rec):
        kind = rec.kind
        ref = Ref(kind=kind, id=rec.id)
        if kind == "material_link":
            self._add_edge(rec.material, rec.subject, "attaches_to", rec)
        elif kind == "material_relation":
            self._add_edge(rec.subject, rec.related, rec.relation, rec)
        elif kind == "meeting_subject":
            self._add_edge(rec.meeting, rec.item, "considers", rec)
        elif kind == "meeting":
            for conv in rec.committees:
                self._add_edge(conv.committee, ref, "convenes", rec)
        elif kind == "appearance":
            self._add_edge(ref, rec.meeting, "attends", rec)

    def resolve(self, node: Ref | tuple[str, str]):
        key = (node.kind, node.id) if isinstance(node, Ref) else node
        return self._by_ref.get(key)

    def neighbors(
        self,
        node: Ref | tuple[str, str],
        *,
        relation: str | None = None,
        direction: Literal["out", "in", "both"] = "both",
    ) -> list[Ref]:
        key = (node.kind, node.id) if isinstance(node, Ref) else node
        seen: dict[tuple[str, str], Ref] = {}
        if direction in ("out", "both"):
            for rel, target, _ in self._outgoing.get(key, ()):
                if relation is None or rel == relation:
                    seen[(target.kind, target.id)] = target
        if direction in ("in", "both"):
            for rel, source, _ in self._incoming.get(key, ()):
                if relation is None or rel == relation:
                    seen[(source.kind, source.id)] = source
        return list(seen.values())

    def ancestors(
        self,
        node: Ref | tuple[str, str],
        *,
        relation: str | None = "derived_from",
    ) -> list[Ref]:
        start = (node.kind, node.id) if isinstance(node, Ref) else node
        visited: set[tuple[str, str]] = {start}
        order: list[Ref] = []
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for rel, target, _ in self._outgoing.get(current, ()):
                if relation is not None and rel != relation:
                    continue
                t_key = (target.kind, target.id)
                if t_key not in visited:
                    visited.add(t_key)
                    order.append(target)
                    queue.append(t_key)
        return order

    def lineage(self, node: Ref | tuple[str, str]) -> list[Ref]:
        """Return upstream derivation, transcription, redirect, or recovery ancestors."""
        lineage_relations = {"derived_from", "transcribes", "supersedes", "redirected_to", "recovered_from", "linked_ancestor"}
        start = (node.kind, node.id) if isinstance(node, Ref) else node
        visited: set[tuple[str, str]] = {start}
        order: list[Ref] = []
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for rel, target, _ in self._outgoing.get(current, ()):
                if rel not in lineage_relations:
                    continue
                t_key = (target.kind, target.id)
                if t_key not in visited:
                    visited.add(t_key)
                    order.append(target)
                    queue.append(t_key)
        return order

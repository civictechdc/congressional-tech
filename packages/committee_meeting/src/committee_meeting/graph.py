"""Explicit directed graph edges and traversal helpers for committee proceedings."""
from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import model_validator

from .common import Ref, Text
from .provenance import Record

DomainKind = Literal[
    "committee", "committee_term", "channel",
    "meeting", "occurrence", "panel", "person", "appearance",
    "material", "material_version", "representation",
    "legislative_item", "amendment", "amendment_group", "vote",
    "source_record",
]

EdgeRelation = Literal[
    "convenes", "attends", "considers", "attaches_to",
    "transcribes", "derived_from", "supersedes",
    "redirected_to", "recovered_from", "linked_ancestor", "same_proceeding",
    "translation_of", "corrects", "part_of", "alternate_of", "related",
]


class Edge(Record):
    """A directed relationship with independent provenance and optional coverage/metadata."""

    kind: Literal["edge"] = "edge"
    source: Ref[DomainKind]
    target: Ref[DomainKind]
    relation: EdgeRelation = "attaches_to"
    role: str | None = None
    coverage: Literal["full", "partial", "unknown"] = "unknown"
    metadata: dict[str, str | int | float | bool | None] = {}

    @model_validator(mode="after")
    def not_self_referential(self):
        if self.source == self.target:
            raise ValueError(f"{self.id}: relationship cannot target itself")
        return self


class CatalogGraph:
    """Index-backed traversal over a Catalog's records and edges."""

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
        if kind == "edge":
            self._add_edge(rec.source, rec.target, rec.relation, rec)
        elif kind == "material_link":
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
        elif kind == "material":
            for m_id in rec.meeting_ids:
                self._add_edge(ref, Ref(kind="meeting", id=m_id), "attaches_to", rec)
            for a_id in rec.appearance_ids:
                self._add_edge(ref, Ref(kind="appearance", id=a_id), "attaches_to", rec)
            for c_id in rec.committee_ids:
                self._add_edge(ref, Ref(kind="committee_term", id=c_id), "attaches_to", rec)
            for act_id in rec.action_ids:
                for act_kind in ("amendment", "vote", "legislative_item", "amendment_group"):
                    if (act_kind, act_id) in self._by_ref:
                        self._add_edge(ref, Ref(kind=act_kind, id=act_id), "attaches_to", rec)
                        break

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

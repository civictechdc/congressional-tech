from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class CommitteeSummary:
    chamber: str
    committeeTypeCode: str
    name: str
    systemCode: str
    url: str
    updateDate: datetime

    # Relations (not included in dataclass-generated __repr__ to avoid cycles)
    parent: Optional[CommitteeSummary] = field(default=None, repr=False)
    children: List[CommitteeSummary] = field(default_factory=list, repr=False)

    # -------------------- Relationship helpers --------------------
    def set_parent(self, parent: Optional[CommitteeSummary]) -> None:
        """Assign a parent and keep bidirectional links consistent.
        If parent is None, the committee becomes a root.
        """
        if parent is self:
            raise ValueError("A committee cannot be its own parent")

        # If we're already under this parent, nothing to do
        if parent is not None and self.parent is parent:
            return

        # Detach from current parent if needed
        if self.parent is not None:
            try:
                self.parent.children.remove(self)
            except ValueError:
                pass

        # Attach to new parent
        self.parent = parent
        if parent is not None and self not in parent.children:
            parent.children.append(self)

    def add_child(self, child: CommitteeSummary) -> None:
        """Add a child and keep bidirectional links consistent."""
        if child is self:
            raise ValueError("A committee cannot be its own child")
        if child not in self.children:
            self.children.append(child)
        # Ensure the child's parent is this
        if child.parent is not self:
            child.set_parent(self)

    # -------------------- Navigation helpers --------------------
    def ancestors(self) -> List[CommitteeSummary]:
        cur = self.parent
        out: List[CommitteeSummary] = []
        while cur is not None:
            out.append(cur)
            cur = cur.parent
        return out

    def descendants(self) -> List[CommitteeSummary]:
        out: List[CommitteeSummary] = []
        stack = list(self.children)
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(node.children)
        return out

    def root(self) -> CommitteeSummary:
        cur = self
        while cur.parent is not None:
            cur = cur.parent
        return cur

    # -------------------- (De)serialization --------------------
    @staticmethod
    def parse_date(value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        # Congress API provides Zulu suffix
        return datetime.strptime(value, ISO_FMT)

    @classmethod
    def from_dict(
        cls, data: Dict, index: Optional[CommitteeSummaryIndex] = None
    ) -> CommitteeSummary:
        """Create (or fetch+update) a CommitteeSummary from a JSON-like dict.
        If an `index` is provided, instances are deduped by systemCode and
        parent/child links are established bidirectionally.
        """
        # Extract fields, allowing partial payloads
        chamber = data.get("chamber")
        ctype = data.get("committeeTypeCode")
        name = data.get("name")
        system_code = data.get("systemCode")
        url = data.get("url")
        update = (
            cls.parse_date(data.get("updateDate")) if data.get("updateDate") else None
        )

        if index is None:
            inst = cls(
                chamber=chamber,
                committeeTypeCode=ctype,
                name=name,
                systemCode=system_code,
                url=url,
                updateDate=update or datetime.min,
            )
        else:
            inst = index.get_or_create(
                system_code,
                default=lambda: cls(
                    chamber=chamber,
                    committeeTypeCode=ctype,
                    name=name,
                    systemCode=system_code,
                    url=url,
                    updateDate=update or datetime.min,
                ),
            )
            # Update basic fields if present
            if chamber is not None:
                inst.chamber = chamber
            if ctype is not None:
                inst.committeeTypeCode = ctype
            if name is not None:
                inst.name = name
            if url is not None:
                inst.url = url
            if update is not None:
                inst.updateDate = update

        # Link parent if present
        parent_data = data.get("parent")
        if parent_data:
            parent_code = parent_data.get("systemCode")
            if index is None:
                parent = cls.from_dict(parent_data)  # standalone mode
            else:
                parent = index.get_or_create(
                    parent_code,
                    default=lambda: cls(
                        chamber=parent_data.get("chamber", chamber),
                        committeeTypeCode=parent_data.get("committeeTypeCode", ctype),
                        name=parent_data.get("name"),
                        systemCode=parent_code,
                        url=parent_data.get("url"),
                        updateDate=cls.parse_date(parent_data.get("updateDate"))
                        if parent_data.get("updateDate")
                        else datetime.min,
                    ),
                )
                # Update parent name/url if provided
                if parent_data.get("name"):
                    parent.name = parent_data["name"]
                if parent_data.get("url"):
                    parent.url = parent_data["url"]
                if parent_data.get("committeeTypeCode"):
                    parent.committeeTypeCode = parent_data["committeeTypeCode"]
                if parent_data.get("chamber"):
                    parent.chamber = parent_data["chamber"]
                if parent_data.get("updateDate"):
                    parent.updateDate = cls.parse_date(parent_data["updateDate"])  # type: ignore[arg-type]

            inst.set_parent(parent)

        return inst

    def to_dict(self, include_tree: bool = False) -> Dict:
        d = {
            "chamber": self.chamber,
            "committeeTypeCode": self.committeeTypeCode,
            "name": self.name,
            "systemCode": self.systemCode,
            "url": self.url,
            "updateDate": self.updateDate.strftime(ISO_FMT),
        }
        if include_tree:
            if self.parent is not None:
                d["parent"] = {
                    "systemCode": self.parent.systemCode,
                    "name": self.parent.name,
                    "url": self.parent.url,
                }
            if len(self.children) > 0:
                d["children"] = [
                    {
                        "systemCode": c.systemCode,
                        "name": c.name,
                        "url": c.url,
                    }
                    for c in self.children
                ]
        return d


class CommitteeSummaryIndex:
    """Registry for deduping/linking CommitteeSummarys by systemCode."""

    def __init__(self) -> None:
        self._by_code: Dict[str, CommitteeSummary] = {}

    def get(self, system_code: str) -> Optional[CommitteeSummary]:
        return self._by_code.get(system_code)

    def get_or_create(self, system_code: str, default) -> CommitteeSummary:
        inst = self._by_code.get(system_code)
        if inst is None:
            inst = default()
            self._by_code[system_code] = inst
        return inst

    def upsert_from_dict(self, data: Dict) -> CommitteeSummary:
        return CommitteeSummary.from_dict(data, index=self)

    def link_parent(self, child_code: str, parent_code: Optional[str]) -> None:
        child = self._by_code.get(child_code)
        parent = self._by_code.get(parent_code) if parent_code else None
        if child is None:
            raise KeyError(f"Unknown committee: {child_code}")
        child.set_parent(parent)

    def roots(self) -> List[CommitteeSummary]:
        return [c for c in self._by_code.values() if c.parent is None]

    def all(self) -> List[CommitteeSummary]:
        return list(self._by_code.values())

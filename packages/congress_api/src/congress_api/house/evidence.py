"""Source-shaped House XML evidence, alongside the existing recovery CSV rows.

Selectors address the retained observation, not a permanent document or person
identity. Source dates and URLs keep their original spelling and precision.
"""

from congress_api.house.repository import NAME, active, value
from congress_api.inventory.common import text

SCHEMA_VERSION = "1.0"


def metadata(element, *, omit=()):
    """Retain attributes, repeated children and source order without raw XML."""
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": element.text or "",
        "tail": element.tail or "",
        "children": [metadata(child) for child in element if child.tag not in omit],
    }


def document_group(element, source, selector, order, owner=None, owner_active=True):
    return {
        "source": source,
        "selector": selector,
        "source_order": order,
        "owning_witness_selector": owner,
        "active": owner_active and active(element),
        "type": element.get("type") or value(element, "type") or value(element, "filename-metadata/doc-type") or value(element, "filename-metadata/type"),
        "description": value(element, "description") or value(element, "filename-metadata/description"),
        "metadata": metadata(element, omit=("files",)),
        "files": [
            {
                "selector": f"{selector}/files/file[{index}]",
                "url": file.get("doc-url", ""),
                "format": file.get("doc-type", ""),
                "active": owner_active and active(element) and active(file),
                "metadata": metadata(file),
            }
            for index, file in enumerate(element.findall("files/file"), 1)
        ],
    }


def retained_evidence(root, wlist, page=""):
    """All XML observations, including removed rows omitted from current CSVs."""
    groups, panels, witnesses = [], [], []
    if root is not None:
        for index, document in enumerate(root.findall("meeting-documents/meeting-document"), 1):
            groups.append(document_group(document, "meeting_xml", f"/committee-meeting/meeting-documents/meeting-document[{index}]", index))
    if wlist is not None:
        for panel_index, panel in enumerate(wlist.findall("panel"), 1):
            panel_selector = f"/witness-list/panel[{panel_index}]"
            panels.append({
                "selector": panel_selector, "source_order": panel_index,
                "sort_order": panel.get("sort-order", ""), "active": active(panel),
                "metadata": metadata(panel, omit=("witness",)),
            })
            for witness_index, witness in enumerate(panel.findall("witness"), 1):
                selector = f"{panel_selector}/witness[{witness_index}]"
                witnesses.append({
                    "selector": selector, "panel_selector": panel_selector,
                    "source_order": witness_index, "display_order": witness.get("display-order", ""),
                    "active": active(panel) and active(witness),
                    "name": text(" ".join(value(witness, tag) for _, tag in NAME)),
                    "metadata": metadata(witness, omit=("witness-documents",)),
                })
                for index, document in enumerate(witness.findall("witness-documents/witness-document"), 1):
                    groups.append(document_group(document, "witness_xml", f"{selector}/witness-documents/witness-document[{index}]", index,
                                                 selector, active(panel) and active(witness)))
    return {
        "schema_version": SCHEMA_VERSION,
        "meeting_metadata": metadata(root, omit=("meeting-documents",)) if root is not None else None,
        "witness_list_metadata": metadata(wlist, omit=("panel",)) if wlist is not None else None,
        "document_groups": groups, "panels": panels, "witness_observations": witnesses,
        "limitations": (["HTML fallback retains legacy extracted rows only; XML grouping, ownership and source metadata are unavailable."]
                        if page and (root is None or wlist is None) else []),
    }

"""Source-shaped House XML evidence, alongside the existing recovery CSV rows.

Selectors address the retained observation, not a permanent document or person
identity. Source dates and URLs keep their original spelling and precision.
"""

import re

from lxml import html

from congress_api.models.house import HouseEvidence
from congress_api.models.xml import XmlElement
from congress_api.parsers.house_documents import NAME, active, document_kind, documents, value
from congress_api.parsers.house_documents import witnesses as page_witnesses
from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses
from congress_api.parsers.text import text

SCHEMA_VERSION = "1.1"


def html_document_groups(page):
    """Keep every explicitly linked rendition in each fallback page list item."""
    legacy = {url: (kind, name) for kind, name, url in documents(page)}
    tree = html.fromstring(page)
    for index, item in enumerate(tree.xpath("//li"), 1):
        links = [a for a in item.xpath(".//a[@href]") if re.fullmatch(r"PDF|XML|DOCX?|HTML?|XLSX?|RTF|TXT", a.text_content().strip(), re.I)
                 and a.xpath("ancestor::li[1]")[0] == item]
        if not links:
            continue
        files = [{"url": link.get("href"), "format": link.text_content().strip(), "active": True,
                  "metadata": {"attributes": dict(link.attrib)}} for link in links]
        preferred = next((file["url"] for file in files if file["format"].upper() == "PDF"), files[0]["url"])
        kind, name = legacy.get(preferred.replace("http://", "https://"), ("", text(item.text_content().split("[", 1)[0])))
        yield {"source": "html", "source_order": index, "active": True, "selector": f"//li[{index}]",
               "legacy_kind": kind or document_kind("", name, preferred), "description": name,
               "metadata": {"attributes": dict(item.attrib)}, "files": files}


def metadata(element, *, omit=()):
    """Retain attributes, repeated children and source order without raw XML."""
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": element.text or "",
        "tail": element.tail or "",
        "children": [metadata(child) for child in (element.children if isinstance(element, XmlElement) else element) if child.tag not in omit],
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


def parse_retained_evidence(root, wlist, page="") -> HouseEvidence:
    """All XML observations, including removed rows omitted from current CSVs."""
    root = parse_house_meeting(root) if root is not None else None
    wlist = parse_house_witnesses(wlist) if wlist is not None else None
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
    if page:
        groups.extend(html_document_groups(page))
        for index, (name, position, organization, panel) in enumerate(page_witnesses(page), 1):
            witnesses.append({"name": name, "position": position, "organization": organization,
                              "panel": panel, "source_order": index, "active": True, "source": "html"})
    return HouseEvidence.model_validate({
        "schema_version": SCHEMA_VERSION,
        "meeting_metadata": metadata(root, omit=("meeting-documents",)) if root is not None else None,
        "witness_list_metadata": metadata(wlist, omit=("panel",)) if wlist is not None else None,
        "document_groups": groups, "panels": panels, "witness_observations": witnesses,
        # Retain the fallback body: extracted rows cannot preserve every source
        # label or establish document ownership after the HTML was flattened.
        **({"html": page} if page else {}),
        "limitations": (["HTML fallback retains its body and extracted rows; XML grouping and witness-document ownership are unavailable."]
                        if page and (root is None or wlist is None) else []),
    })


def retained_evidence(root, wlist, page=""):
    return parse_retained_evidence(root, wlist, page).source_dict()

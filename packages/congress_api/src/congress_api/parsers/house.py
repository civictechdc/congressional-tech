"""Interpret supplied House XML and HTML as a typed meeting record."""

from congress_api.models.content import RawContent
from congress_api.models.house import HouseParsedRecord
from congress_api.parsers.house_documents import (
    WITNESS_FIELDS,
    documents,
    read_xml,
    witness_area,
    witness_rows,
    witnesses,
)
from congress_api.parsers.house_evidence import parse_retained_evidence
from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses


def parse_house_record(root, wlist, page, wstatus) -> HouseParsedRecord:
    root = parse_house_meeting(root) if root is not None else None
    wlist = parse_house_witnesses(wlist) if wlist is not None else None
    docs, amendments = read_xml(root, wlist) if root is not None else ([], [])
    listed = witness_rows(wlist) if wlist is not None else []
    fallback = page if root is None else witness_area(page) if wstatus == "unfetched" else ""
    if fallback:
        docs += [(k, n, u, {u.rsplit("/", 1)[-1]}) for k, n, u in documents(fallback)]
        listed = [dict(zip(WITNESS_FIELDS[1:5], w)) for w in witnesses(page)]
    bodies = {name: node.raw_content for name, node in (("meeting_xml", root), ("witness_xml", wlist))
              if node is not None and node.raw_content is not None}
    if page:
        bodies['page_html'] = RawContent.from_bytes(page.encode('utf-8'), 'text/html')
    return HouseParsedRecord.model_validate({"documents": [[k, n, u, sorted(files)] for k, n, u, files in docs], "witnesses": listed,
            "amendments": amendments, "xml_update": root.get("update-date", "") if root is not None else "",
            "status": "xml" if root is not None else "page" if page else "absent", "witness_status": wstatus,
            "evidence": parse_retained_evidence(root, wlist, fallback), **({"source_bodies": bodies} if bodies else {})})


def parsed(root, wlist, page, wstatus):
    return parse_house_record(root, wlist, page, wstatus).source_dict()

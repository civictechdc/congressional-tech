"""Explorer document categories, separate from literal meanings and filename kinds.

House XML and Congress.gov meeting adapters share this output policy. Source
interpretation stays in parsers.document_types; filename families stay in
house_naming.categories.
"""

from congress_api.parsers.document_types import DOCUMENT_TYPE_MEANINGS, document_type


# The normalized meeting schema intentionally groups several native document types.
DOCUMENT_CATEGORIES = {
    "witness-statement": "statement", "member-statement": "statement",
    "testimony-disclosure": "disclosure", "witness-biography": "biography",
    "witness-support": "supporting", "support-document": "supporting", "summary": "supporting",
    "committee-amendment": "amendment", "interchamber-amendment": "amendment", "floor-amendment": "amendment",
    "committee-vote": "vote", "committee-report": "report", "conference-report": "report",
    "legislative-text": "bill_text", "transcript": "transcript", "witness-list": "witness_list",
    "questions-for-record": "questions_for_record", "member-roster": "hearing_record",
    "cover-page": "hearing_record", "table-of-contents": "hearing_record",
}


def category(row):
    native = str(row.get("documentType") or row.get("kind") or "").strip().lower()
    # These labels describe the document itself; a title mentioning a bill or
    # witness must not replace the publisher's more specific classification.
    # Preserve this consumer's existing priority: these specific literal labels
    # outrank titles; generic types still permit its historical title fallback.
    explicit_labels = {
        "hearing: questions for the record", "committee report", "conference report",
        "hearing: member roster", "hearing: cover page", "hearing: table of contents",
        "legislative text", "committee amendment", "summary",
    }
    meaning = document_type(native)
    if native in explicit_labels and meaning in DOCUMENT_CATEGORIES:
        return DOCUMENT_CATEGORIES[meaning]
    text = f"{row.get('documentType', '')} {row.get('kind', '')} {row.get('name', '')}".lower()
    for needle, value in (("truth in testimony", "disclosure"), ("transcript", "transcript"), ("witness list", "witness_list"), ("statement", "statement"),
                          ("testimony", "statement"), ("biograph", "biography"), ("disclosure", "disclosure"),
                          ("amendment", "amendment"), ("vote", "vote"), ("bill", "bill_text")):
        if needle in text:
            return value
    return "supporting" if native == "support document" else "unknown"


# SD is deliberately absent: its description can supply a more specific category.
HOUSE_DOCUMENT_CATEGORIES = {
    alias.upper(): DOCUMENT_CATEGORIES[meaning]
    for alias, meaning in DOCUMENT_TYPE_MEANINGS.items()
    if len(alias) == 2 and alias != "sd" and meaning in DOCUMENT_CATEGORIES
}

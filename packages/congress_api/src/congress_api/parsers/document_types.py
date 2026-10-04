"""Literal House XML codes and publisher labels, independent of output categories.

A meaning identifies the publisher's document type. Consumers map these meanings
into their own coarse meeting categories or detailed retained-file kinds.
"""

DOCUMENT_TYPE_MEANINGS = {
    alias.casefold(): kind
    for kind, aliases in [
        ("witness-statement", ("Witness Statement", "WS")),
        ("testimony-disclosure", ("Witness Truth in Testimony", "truth in testimony", "WT")),
        ("witness-biography", ("Witness Biography", "WB")),
        ("witness-support", ("Witness Support Document", "WD")),
        ("member-statement", ("Member Statement", "Member Statements", "MS")),
        ("committee-amendment", ("Committee Amendment", "CA")),
        ("interchamber-amendment", ("House or Senate Amendment", "HA")),
        ("floor-amendment", ("Floor Amendment", "FA")),
        ("committee-vote", ("Committee Recorded Vote", "CV")),
        ("committee-report", ("Committee Report", "CR")),
        ("conference-report", ("Conference Report", "FR")),
        ("legislative-text", ("Bills and Resolutions", "BR", "legislative text")),
        ("summary", ("summary",)),
        ("support-document", ("Support Document", "SD")),
        ("transcript", ("Hearing: Transcript", "transcript", "HT")),
        ("witness-list", ("Hearing: Witness List", "witness list", "HW")),
        ("questions-for-record", ("Hearing: Questions for the Record", "questions for the record", "HQ")),
        ("member-roster", ("Hearing: Member Roster", "HM")),
        ("cover-page", ("Hearing: Cover Page", "HC")),
        ("table-of-contents", ("Hearing: Table of Contents", "TC")),
        ("questionnaire", ("questionnaire",)),
    ]
    for alias in aliases
}


def document_type(value: object) -> str | None:
    """Return a recognized literal meaning; titles and filenames are not evidence here."""
    if not isinstance(value, str):
        return None
    return DOCUMENT_TYPE_MEANINGS.get(' '.join(value.split()).casefold())

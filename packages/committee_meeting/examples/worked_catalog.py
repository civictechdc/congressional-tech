"""Synthetic design example, not a claim about real congressional proceedings.

From the repository root:
  PYTHONPATH=packages/committee_meeting/src .venv/bin/python packages/committee_meeting/examples/worked_catalog.py
"""
from committee_meeting import Catalog


def reference(kind, id):
    return {"kind": kind, "id": id}


def worked_catalog() -> Catalog:
    evidence = {"basis": "reported", "citations": [{"source": reference("source_record", "synthetic")}]}
    records = []

    def add(kind, id, **fields):
        records.append({"kind": kind, "id": id, "provenance": evidence, **fields})

    for letter in ("a", "b"):
        add("committee", f"committee-{letter}", label=f"Example committee {letter.upper()}")
        add("committee_term", f"term-{letter}", committee=reference("committee", f"committee-{letter}"),
            congress=119, name=f"Example committee {letter.upper()}", chamber="house")

    committees = [{"committee": reference("committee_term", f"term-{letter}"), "role": "cohost",
                   "provenance": evidence} for letter in ("a", "b")]
    add("meeting", "hearing", title="Example joint hearing", congress=119, chamber="house",
        meeting_type="hearing", committees=committees)
    add("meeting", "markup", title="Example markup", congress=119, chamber="house",
        meeting_type="markup", committees=committees[:1])
    for day in (1, 2):
        add("occurrence", f"day-{day}", meeting=reference("meeting", "hearing"), status="held",
            actual_start={"date": f"2026-09-0{day}"})
    add("panel", "panel", meeting=reference("meeting", "hearing"),
        occurrence=reference("occurrence", "day-1"), label="Panel I")
    for letter in ("a", "b"):
        add("appearance", f"witness-{letter}", meeting=reference("meeting", "hearing"),
            panel=reference("panel", "panel"), name={"display": "Alex Example"}, roles=["witness"],
            participation="listed", affiliation={"organization_name": f"Organization {letter.upper()}"})

    # A printed transcript is valid without any video. Two proceedings share it.
    add("material", "print", title="Combined hearing record", details={"type": "document", "category": "transcript"})
    add("material_version", "print-v1", material=reference("material", "print"), label="First edition")
    add("material_version", "print-v2", material=reference("material", "print"),
        label="Corrected edition", supersedes=reference("material_version", "print-v1"))
    for format, media in (("pdf", "application/pdf"), ("html", "text/html"), ("xml", "application/xml")):
        add("representation", f"print-{format}", version=reference("material_version", "print-v2"),
            format_label=format.upper(), media_type=media,
            locations=[{"url": f"https://example.org/record.{format}", "role": "download"}])
    for meeting, start, end in (("hearing", 1, 20), ("markup", 21, 35)):
        add("material_link", f"print-{meeting}", material=reference("material", "print"),
            version=reference("material_version", "print-v2"), subject=reference("meeting", meeting),
            role="transcript", extent={"representation": reference("representation", "print-pdf"),
                                      "first_page": start, "last_page": end})

    # Discoverable without a matched meeting, and without assuming downloadable media.
    add("material", "archive-video", title="Unlinked archival recording",
        details={"type": "recording", "medium": "video", "provider": "senate-isvp"})
    add("material_version", "archive-v1", material=reference("material", "archive-video"))
    add("representation", "archive-player", version=reference("material_version", "archive-v1"),
        locations=[{"url": "https://example.org/player", "role": "player"}])
    inferred = {**evidence, "basis": "inferred", "method": {"name": "example-caption-date-rule", "version": "1"}}
    add("assessment", "caption-estimate", subject=reference("material", "archive-video"),
        aspect="captions", status="available", evaluated_at="2026-09-27T12:00:00Z",
        provenance=inferred, explanation="Illustrative availability inference; no track identified or bytes retained.")

    add("legislative_item", "bill", congress=119, item_type="bill", designation="H.R. 99999")
    add("meeting_subject", "markup-bill", meeting=reference("meeting", "markup"),
        item=reference("legislative_item", "bill"), relationship="considered")
    add("amendment", "amendment-1", meeting=reference("meeting", "markup"),
        target=reference("legislative_item", "bill"), number="1")
    add("amendment", "amendment-2", meeting=reference("meeting", "markup"),
        target=reference("amendment", "amendment-1"), number="2")
    add("amendment_group", "enbloc", meeting=reference("meeting", "markup"), label="En bloc 1",
        members=[reference("amendment", "amendment-1"), reference("amendment", "amendment-2")])
    add("vote", "vote-1", meeting=reference("meeting", "markup"),
        subject=reference("amendment_group", "enbloc"), number="1")

    return Catalog.model_validate({"sources": [{
        "id": "synthetic", "provider": "example", "identifier": {"scheme": "example", "value": "worked-catalog"},
        "payload": {"notice": "All records in this example are synthetic."},
    }], "records": records})


if __name__ == "__main__":
    print(worked_catalog().model_dump_json(indent=2, exclude_none=True))

"""Choose House meeting XML URLs and select missing document renditions."""

import collections
import re

from congress_api.parsers.house_documents import document_kind, value

## a meeting file's name: prefix, Congress, committee, then the day, at once or after the document's own name
FILED = re.compile(r"^(H[A-Z]{3})-(\d{3})-([A-Z]{2}\w{2})-(?:[^.]*?-)?(\d{8})(?=[-.])")


def addresses(m, root=None, page=""):
    """Where a meeting's XML can be. From the record: the prefix, committee and day its documents' file names carry
    (HHRG-115-AS26-Wstate-ManfraJ-20181114.pdf), on the record or the page, commonest first; then the folder a
    document is in (.../RU/RU00/20150226/103102/CRPT-114-RU00-Vote029-20150226.pdf); then its type, committee
    and date. Where the prefix is not named, all three are tried, the meeting's type's first. A joint hearing is filed under one of its committees and a
    rescheduled one under either day (108754 is Homeland Security's record, filed under Armed Services' AS26), so
    the file names come first. From a cached meeting file: its own prefix, with the directory its documents
    are in, then each committee and subcommittee it names: a meeting of a committee and its subcommittee is filed
    under either (103995 lists AS00 and AS26 and is filed under AS00)."""
    if root is not None:
        prefix, congress = root.get("meeting-type"), root.get("congress-num")
        ## A document's directory preserves the original date even if the meeting was rescheduled.
        directory = re.compile(r"https?://docs\.house\.gov/meetings/([A-Z]{2})/([A-Z]{2}\w{2})/(\d{8})/" + re.escape(m["eventId"]) + "/")
        day = value(root, "meeting-details/meeting-date/calendar-date").replace("-", "")
        places = [(d[2], d[3]) for f in root.iter("file") if (d := directory.search(f.get("doc-url", "")))]
        places += [(c.get("id", ""), day) for c in root.findall("meeting-details/committees/committee-name") + root.findall("meeting-details/subcommittees/committee-name")]
        return list(dict.fromkeys(f"https://docs.house.gov/meetings/{code[:2]}/{code}/{d}/{m['eventId']}/{prefix}-{congress}-{code}-{d}.xml" for code, d in places if code and d))
    links = [d.get("url") or "" for d in (m.get("meetingDocuments") or []) + (m.get("witnessDocuments") or [])] + re.findall(r"href=\"([^\"]+)\"", page)
    named = collections.Counter(f.groups() for u in links if (f := FILED.search(u.rsplit("/", 1)[-1])))
    found = [f"https://docs.house.gov/meetings/{code[:2]}/{code}/{day}/{m['eventId']}/{prefix}-{congress}-{code}-{day}.xml" for (prefix, congress, code, day), _ in named.most_common()]
    folders = [f.groups() for u in links if (f := re.search(r"/meetings/[A-Z]{2}/([A-Z]{2}\w{2})/(\d{8})/" + re.escape(m["eventId"]) + "/", u))]
    ## House codes: hs for standing committees, hl for Intelligence and the select committees (hlig00 is IG00)
    code = next((c["systemCode"][2:].upper() for c in m.get("committees", []) if re.match(r"h[sl]", c.get("systemCode", ""))), "")
    places = [p for p, _ in collections.Counter(folders).most_common()] + ([(code, m.get("date", "")[:10].replace("-", ""))] if code else [])
    prefix = {"Hearing": "HHRG", "Markup": "HMKP"}.get(m.get("type"), "HMTG")
    built = [f"https://docs.house.gov/meetings/{c[:2]}/{c}/{day}/{m['eventId']}/{p}-{m.get('congress')}-{c}-{day}.xml"
             for c, day in places if day for p in [prefix] + [p for p in ("HHRG", "HMKP", "HMTG") if p != prefix]]
    return list(dict.fromkeys(found + built))

DOCUMENT_FIELDS = "event_id kind name url document_type source_group source_selector owning_witness_selector add_date publish_date".split()


def document_rows(saved, event, have=()):
    """Compact recovery report: one row per file missing from the API listing.

    Congress.gov mirrors House files under a different URL, so this report uses
    filenames within the same meeting to suppress already-listed renditions.
    Compare each format separately: a listed PDF cannot suppress its XML. Full
    source URLs, metadata, removed entries and grouping remain in gzip state;
    this report's overlap check does not merge material identities.
    """
    normalize = lambda url: url.replace("http://", "https://")
    have = {normalize(url).rsplit("/", 1)[-1] for url in have}
    groups = saved.get("evidence", {}).get("document_groups")
    if groups is None:
        groups = [{"legacy_kind": kind, "description": name, "files": [{"url": url}]}
                  for kind, name, url, _ in saved.get("documents", [])]
    owners = {w.get("selector"): w.get("name", "") for w in saved.get("evidence", {}).get("witness_observations", []) if w.get("selector")}
    for group in groups:
        if not group.get("active", True):
            continue
        files = [file for file in group.get("files", []) if file.get("active", True) and file.get("url")]
        code, description = group.get("type", ""), group.get("description", "")
        owner = owners.get(group.get("owning_witness_selector"))
        attributes = group.get("metadata", {}).get("attributes", {})
        for file in files:
            url = normalize(file["url"])
            if url.rsplit("/", 1)[-1] in have:
                continue
            kind = group.get("legacy_kind") or document_kind(code, description, url)
            yield {"event_id": event, "kind": kind,
                   "name": description or (f"{kind}: {owner}" if owner else url.rsplit("/", 1)[-1]), "url": url,
                   "document_type": code, "source_group": group.get("source", ""),
                   "source_selector": group.get("selector", ""), "owning_witness_selector": group.get("owning_witness_selector") or "",
                   "add_date": attributes.get("add-date", ""), "publish_date": attributes.get("publish-date", "")}

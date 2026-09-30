"""Select missing House document renditions for the recovery report."""

from congress_api.parsers.house_documents import document_kind

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

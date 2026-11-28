"""Prepare one published congressional archive for SpicyEngine and install it on the local runtime."""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from collections import Counter
from contextlib import closing
from hashlib import file_digest, sha256
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb
import pyarrow.parquet as pq

from congress_shared.custody import write_atomic_bytes
from viewer_publication import passage_keywords
from viewer_publication.archive_format import release_identity

ORIGIN = "https://congressional-data.spicygov.ai"
RECIPE = "search-v3"
STAGED_ARCHIVE_KEY = "viewer-publications/staged.json"
STAGED_TEXT_KEY = "derived/body_text/staged.json"
FIELDS = {
    "title": "title", "text": ["body"], "url": "source_url", "identifiers": "identifiers",
    "page_offsets": {"body": "page_offsets"},
    "date_default": "document_date",
    "labels": {"committee_keys": "Committees", "document_kind": "Document kind",
               "document_family": "Document family", "document_date": "Document date",
               "chambers": "Chambers", "text_status": "Text coverage", "archive_title": "Archive title",
               "page_offsets": "Page offsets (UTF-8 bytes)", "saved_body_sha256": "Archived file SHA-256",
               "text_sha256": "Selected text SHA-256", "member_path": "File inside source archive"},
}
_MACHINE_LISTED_ON_RE = (
    r"(?i)(?:^https?://api\."
    r"|^https?://(?:www\.)?govinfo\.gov/metadata/pkg/[^/?#]+/mods\.xml(?:[?#].*)?$"
    r"|/wp-json(?:/|[?#]|$))"
)
_CONGRESS_MEETING_API_RE = (
    r"(?i)^https?://api\.congress\.gov/v3/committee-meeting/([0-9]+)/(house|senate)/([0-9]+)(?:/|[?#].*)?$"
)
_GOVINFO_METADATA_API_RE = (
    r"(?i)^https?://(?:api\.govinfo\.gov/packages|www\.govinfo\.gov/metadata/pkg)/"
    r"([^/?#]+)/(?:mods|mods\.xml|summary)(?:[?#].*)?$"
)
_CONGRESS_HEARING_API_RE = r"(?i)^https?://api\.congress\.gov/v3/hearing/"
_NON_TITLE_TEXT_RE = (
    r"(?i)(?:^(?:zip|pdf|html?|xml|docx?|txt|text|json|csv|xlsx?|pptx?|rtf|mp3|mp4)[.!:]*$"
    r"|^(?:(?:please\s+)?click\s+here\b.*|here|link|document|file|download(?:\s+.*)?"
    r"|(?:view|open)(?:\s+(?:witness\s+)?(?:testimony|statement|document|pdf|file|results|text)\b.*)?"
    r"|read\s+more|more|email|print|share|website|webpage|untitled|attachment|hearings?"
    r"|printable\s+(?:pdf|version)(?:\s+of\s+this\s+(?:document|page))?)[.!:]*$"
    r"|^[\s\W\d_]*(?:(?:zip|pdf|html?|xml|docx?|txt|text|json|csv|xlsx?|pptx?|rtf|mp3|mp4"
    r"|download|view|open|click|here|[kmg]i?b|bytes?)\b[\s\W\d_]*)+$"
    r"|^(?:[^A-Za-z]*|(?:nos?|number)[.]?[^A-Za-z]*[0-9][^A-Za-z]*|_[0-9]+(?:\s*\([^)]*\)?[,;.!:]*)?)$"
    r"|^(?:(?:H\.?\s?R\.?|S\.|H\.?\s?Res\.?|S\.?\s?Res\.?|H\.?\s?J\.?\s?Res\.?|S\.?\s?J\.?\s?Res\.?"
    r"|H\.?\s?Con\.?\s?Res\.?|S\.?\s?Con\.?\s?Res\.?)\s*|S\s+)_+(?:\.[A-Za-z0-9]{2,5})?[,;.!:]*$"
    r"|^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement"
    r"|testimony|biography|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$"
    r"|^\S+\.(?:pdf|docx?|xlsx?|pptx?|zip|xml|txt|csv|rtf|html?)$"
    r"|^https?://)"
)
_CONGRESS_EVENT_URL_SQL = f"""'https://www.congress.gov/event/' ||
    regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 1) ||
    CASE WHEN try_cast(regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 1) AS INTEGER) % 100 IN (11, 12, 13) THEN 'th'
         WHEN try_cast(regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 1) AS INTEGER) % 10 = 1 THEN 'st'
         WHEN try_cast(regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 1) AS INTEGER) % 10 = 2 THEN 'nd'
         WHEN try_cast(regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 1) AS INTEGER) % 10 = 3 THEN 'rd'
         ELSE 'th' END ||
    '-congress/' || lower(regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 2)) ||
    '-event/' || regexp_extract(listed_on, '{_CONGRESS_MEETING_API_RE}', 3)"""
MEETING_REF_TITLES = f"""CREATE TEMPORARY TABLE meeting_ref_titles AS
WITH refs AS (
    SELECT unnest(document_references) AS r FROM read_parquet(?)
),
cleaned AS (
    SELECT r.url, r.ordinal,
           nullif(trim(regexp_replace(
               coalesce(nullif(trim(r.name), ''), nullif(trim(r.description), '')),
               '\\s+', ' ', 'g'
           )), '') AS raw_title
    FROM refs
    WHERE r.url IS NOT NULL
)
SELECT url,
       arg_min(raw_title, ordinal) FILTER (
           WHERE raw_title IS NOT NULL
             AND length(raw_title) >= 4
             AND NOT regexp_matches(raw_title, '{_NON_TITLE_TEXT_RE}')
       ) AS ref_title
FROM cleaned
GROUP BY url
HAVING ref_title IS NOT NULL
"""
EMPTY_MEETING_REF_TITLES = (
    "CREATE TEMPORARY TABLE meeting_ref_titles (url VARCHAR, ref_title VARCHAR)"
)
DOCUMENTS = f"""CREATE TEMPORARY TABLE documents AS
WITH raw_sources AS (
    SELECT file_row_number - ordinal AS src_start, ordinal, url, member_path, is_saved, listed_on, link_text,
           nullif(trim(regexp_replace(link_text, '\\s+', ' ', 'g')), '') AS clean_link_text,
           CASE
               WHEN listed_on IS NULL OR listed_on = url OR NOT regexp_matches(listed_on, '^https?://', 'i') THEN NULL
               WHEN NOT regexp_matches(listed_on, '{_MACHINE_LISTED_ON_RE}') THEN listed_on
           END AS human_listed_on,
           CASE
               WHEN listed_on IS NULL OR listed_on = url OR NOT regexp_matches(listed_on, '^https?://', 'i') THEN NULL
               WHEN regexp_matches(listed_on, '{_CONGRESS_MEETING_API_RE}') THEN {_CONGRESS_EVENT_URL_SQL}
               WHEN regexp_matches(listed_on, '{_GOVINFO_METADATA_API_RE}')
                    THEN 'https://www.govinfo.gov/app/details/' || regexp_extract(listed_on, '{_GOVINFO_METADATA_API_RE}', 1)
           END AS mapped_listed_on,
           regexp_matches(coalesce(listed_on, ''), '{_CONGRESS_HEARING_API_RE}') AS has_hearing_api_listed_on
    FROM read_parquet(?, file_row_number=true)
),
sources AS (
    SELECT s.src_start,
           max(s.url) FILTER (WHERE s.ordinal=0) AS publisher_url,
           max(s.link_text) FILTER (WHERE s.ordinal=0) AS link_text,
           arg_min(s.clean_link_text, s.ordinal) FILTER (
               WHERE s.clean_link_text IS NOT NULL
                 AND length(s.clean_link_text) >= 4
                 AND NOT regexp_matches(s.clean_link_text, '{_NON_TITLE_TEXT_RE}')
           ) AS usable_link_text,
           max(s.member_path) FILTER (WHERE s.ordinal=0) AS member_path,
           arg_min(s.human_listed_on, s.ordinal) FILTER (WHERE s.human_listed_on IS NOT NULL) AS human_listed_on,
           arg_min(s.mapped_listed_on, s.ordinal) FILTER (
               WHERE s.mapped_listed_on IS NOT NULL AND s.mapped_listed_on <> s.url
           ) AS mapped_listed_on,
           bool_or(s.has_hearing_api_listed_on) AS has_hearing_api_listed_on,
           arg_min(m.ref_title, s.ordinal) FILTER (WHERE m.ref_title IS NOT NULL) AS meeting_ref_title,
           arg_min(s.url, s.ordinal) FILTER (WHERE s.is_saved AND nullif(s.member_path,'') IS NULL AND
               regexp_matches(s.url, '^https?://', 'i') AND
               NOT regexp_matches(s.url, '[.](zip|gz)([?#].*)?$', 'i')) AS direct_file
    FROM raw_sources s
    LEFT JOIN meeting_ref_titles m ON m.url = s.url
    GROUP BY s.src_start
)
SELECT d.link_key, d.saved_body, d.saved_suffix, d.title AS archive_title, d.filename, d.package_id,
           substr(coalesce(lower(hex(d.saved_body)), lower(hex(d.link_key))), 1, 2) AS shard,
           d.format, d.document_date, d.document_date_status, d.congress, d.chambers, d.committee_keys,
           d.document_kind, d.document_family, s.publisher_url, s.link_text, s.usable_link_text,
           s.meeting_ref_title, s.member_path,
           coalesce(
               CASE WHEN s.human_listed_on IS DISTINCT FROM s.publisher_url THEN s.human_listed_on END,
               CASE WHEN s.mapped_listed_on IS DISTINCT FROM s.publisher_url THEN s.mapped_listed_on END,
               CASE WHEN s.has_hearing_api_listed_on AND nullif(d.package_id, '') IS NOT NULL
                    AND ('https://www.govinfo.gov/app/details/' || d.package_id) IS DISTINCT FROM s.publisher_url
                    THEN 'https://www.govinfo.gov/app/details/' || d.package_id END
           ) AS listed_on,
           CASE WHEN d.format='pdf' THEN coalesce(s.direct_file,
                CASE WHEN d.saved_suffix IN ('', '.pdf') THEN ? || '/bodies/sha256/' ||
                    left(lower(hex(d.saved_body)),2) || '/' || lower(hex(d.saved_body)) || d.saved_suffix END)
           END AS pdf_url
    FROM read_parquet(?) AS d
    LEFT JOIN sources s ON s.src_start = CASE WHEN d.src_len > 0 THEN d.src_start END
    WHERE d.hidden IS NOT TRUE
      AND coalesce(d.format, '') <> 'zip'
"""
PARTITION = """SELECT 'archive-documents'::VARCHAR AS source_id, lower(hex(d.link_key)) AS member_key,
       coalesce(nullif(d.archive_title, ''), nullif(d.meeting_ref_title, ''), nullif(d.usable_link_text, ''),
                nullif(d.filename, ''), nullif(d.link_text, ''), nullif(d.package_id, ''),
                lower(hex(d.link_key))) AS title,
       b.text AS body,
       coalesce(d.publisher_url, 'https://congressional-data.spicygov.ai/bodies/sha256/' ||
                left(lower(hex(d.saved_body)), 2) || '/' || lower(hex(d.saved_body)) || d.saved_suffix) AS source_url,
       CASE WHEN nullif(d.package_id,'') IS NULL THEN []::VARCHAR[] ELSE [d.package_id] END AS identifiers,
       d.listed_on, d.pdf_url, d.document_date, d.document_date_status, d.congress, d.chambers, d.committee_keys,
       d.document_kind, d.document_family, d.format, d.filename, d.archive_title, d.member_path,
       lower(hex(d.saved_body)) AS saved_body_sha256, lower(hex(b.text_sha256)) AS text_sha256, b.page_offsets,
       CASE WHEN b.saved_body IS NULL THEN 'No text in this export'
            WHEN b.text IS NULL THEN 'Null exported text'
            WHEN b.text = '' THEN 'Empty exported text' ELSE 'Selected text' END AS text_status
      FROM (SELECT * FROM read_parquet(?)
            WHERE saved_body BETWEEN from_hex(?) AND from_hex(?)) AS b
      RIGHT JOIN (SELECT * FROM documents WHERE shard=?) AS d ON b.saved_body=d.saved_body"""


def open_object(origin, key, offset=0):
    headers = {"User-Agent": "congressional-tech-release-gate/1", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    return urlopen(Request(f"{origin.rstrip('/')}/{key}", headers=headers), timeout=120)


def fetch_json(origin, key):
    with open_object(origin, key) as response:
        return json.load(response)


def fetch_optional_json(origin, key):
    try:
        return fetch_json(origin, key)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    except URLError as error:
        if isinstance(error.reason, FileNotFoundError):
            return None
        raise
    except FileNotFoundError:
        return None


def save(path, value):
    write_atomic_bytes(path, (json.dumps(value, sort_keys=True) + "\n").encode(), fsync_dir=True)


def resolve(origin, saved=None, *, staged=False, prefer_staged=False, expected_release_id=None):
    if saved and (staged or prefer_staged):
        raise ValueError("Cannot combine saved pin.json with staged resolution")
    if saved:
        pin = json.loads(saved.read_text())
    elif staged:
        archive = fetch_json(origin, STAGED_ARCHIVE_KEY)
        text = fetch_json(origin, STAGED_TEXT_KEY)
        pin = {"release_id": archive["release_id"], "text": text}
    elif prefer_staged:
        live_archive = fetch_optional_json(origin, "viewer-publications/manifest.json")
        staged_archive = fetch_optional_json(origin, STAGED_ARCHIVE_KEY)
        staged_id = staged_archive.get("release_id") if isinstance(staged_archive, dict) else None
        live_id = live_archive.get("release_id") if isinstance(live_archive, dict) else None
        active_staged = (
            isinstance(staged_id, str)
            and re.fullmatch("[0-9a-f]{64}", staged_id) is not None
            and (
                live_archive is None
                or (
                    staged_id != live_id
                    and staged_archive.get("previous_release_id") in (None, live_id)
                )
            )
        )
        if active_staged:
            staged_text = fetch_optional_json(origin, STAGED_TEXT_KEY)
            if isinstance(staged_text, dict) and staged_text.get("release_id") == staged_id:
                text = staged_text
            else:
                current_text = fetch_optional_json(origin, "derived/body_text/current.json")
                if isinstance(current_text, dict) and current_text.get("release_id") == staged_id:
                    text = current_text
                else:
                    raise ValueError("Archive and body-text pointers must identify the same immutable release")
            pin = {"release_id": staged_id, "text": text}
        else:
            archive = live_archive if live_archive is not None else fetch_json(origin, "viewer-publications/manifest.json")
            text = fetch_json(origin, "derived/body_text/current.json")
            pin = {"release_id": archive["release_id"], "text": text}
    else:
        archive = fetch_json(origin, "viewer-publications/manifest.json")
        text = fetch_json(origin, "derived/body_text/current.json")
        pin = {"release_id": archive["release_id"], "text": text}
    release, text = pin["release_id"], pin["text"]
    if (not re.fullmatch("[0-9a-f]{64}", release) or text["release_id"] != release
            or not re.fullmatch("[0-9a-f]{64}", text["sha256"])
            or text["key"] != f"derived/body_text/{text['sha256']}.parquet"):
        raise ValueError("Archive and body-text pointers must identify the same immutable release")
    if expected_release_id is not None and release != expected_release_id:
        raise ValueError(f"Resolved release {release} differs from expected {expected_release_id}")
    return pin


def download(origin, key, target, digest, size):
    """Resume the owned partial at its pinned URL and verify bytes before naming a completed input."""
    target.parent.mkdir(exist_ok=True)
    partial = target.with_suffix(".part")
    with partial.open("a+b") as output:
        offset = output.tell()
        if offset > size:
            raise ValueError(f"Oversized partial download: {partial}")
        output.seek(0)
        hasher = file_digest(output, "sha256") if offset else sha256()
        if offset < size:
            with open_object(origin, key, offset) as response:
                if response.status == 206:
                    if response.headers.get("Content-Range") != f"bytes {offset}-{size - 1}/{size}":
                        raise ValueError(f"Unexpected range for {key}")
                elif offset:
                    output.truncate(0)
                    hasher = sha256()
                    offset = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    if offset + len(chunk) > size:
                        raise ValueError(f"Download exceeds pinned size for {key}")
                    output.write(chunk)
                    hasher.update(chunk)
                    offset += len(chunk)
        if offset != size:
            raise ValueError(f"Incomplete download of {key}; retained {offset} bytes")
        if hasher.hexdigest() != digest:
            partial.replace(partial.with_suffix(".invalid"))
            raise ValueError(f"Downloaded bytes differ from the pin for {key}")
        output.flush()
        os.fsync(output.fileno())
    partial.replace(target)


def source_files(origin, work, pin, local):
    release, text = pin["release_id"], pin["text"]
    prefix = f"viewer-publications/releases/{release}"
    manifest = fetch_json(origin, prefix + "/manifest.json")
    if manifest["release_id"] != release or release_identity(manifest["schema_version"], manifest["files"]) != release:
        raise ValueError("Archive manifest identity differs from the release")
    entries = {f["name"]: f for f in manifest["files"]}
    if text["detail"] != {k: entries["detail.parquet"][k] for k in ("sha256", "size")}:
        raise ValueError("Text export and archive detail pins disagree")
    names = ["detail.parquet", "sources.parquet"]
    for optional in ("committees.parquet", "meetings.parquet"):
        if optional in entries:
            names.append(optional)
    inputs = {name: (f"{prefix}/{name}", entries[name]["sha256"], entries[name]["size"]) for name in names}
    inputs["body_text.parquet"] = (text["key"], text["sha256"], text["bytes"])
    def locate(name):
        if name in ("committees.parquet", "meetings.parquet") and name not in inputs:
            return None  # Older archive releases can omit optional directory or meeting tables.
        key, digest, size = inputs[name]
        target = work / "downloads" / name
        existing = local / name if local else None
        if existing and existing.is_file():
            with existing.open("rb") as stream:
                if existing.stat().st_size != size or file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError(f"Local {name} differs from the selected release")
            target = existing
        elif target.exists():
            if target.stat().st_size != size:
                raise ValueError(f"Incomplete retained download: {name}")
        else:
            download(origin, key, target, digest, size)
        return str(target)
    return locate


def load_documents(db, locate, *, include_meetings=True):
    meetings = locate("meetings.parquet") if include_meetings else None
    if meetings is not None:
        db.execute(MEETING_REF_TITLES, [meetings])
    else:
        db.execute(EMPTY_MEETING_REF_TITLES)
    db.execute(DOCUMENTS, [locate("sources.parquet"), ORIGIN, locate("detail.parquet")])


def prepare_documents(work, locate):
    body = None
    output = work / "prepared"
    output.mkdir(exist_ok=True)
    with closing(duckdb.connect(config={"threads": 1, "preserve_insertion_order": False})) as db:
        load_documents(db, locate, include_meetings=True)
        counts = dict(db.execute("SELECT shard, count(*) FROM documents GROUP BY shard").fetchall())
        total = sum(counts.values())
        if total != db.execute("SELECT count(DISTINCT link_key) FROM documents").fetchone()[0]:
            raise ValueError("Visible document identities are missing or duplicated")
        for shard, expected in sorted((counts or {"00": 0}).items()):
            if not re.fullmatch("[0-9a-f]{2}", shard):
                raise ValueError("Invalid document identity")
            target = output / f"archive-{shard}.parquet"
            if target.exists():
                if pq.read_metadata(target).num_rows != expected:
                    raise ValueError(f"Incomplete retained partition {shard}")
                continue
            tmp = target.with_suffix(".partial")
            if body is None:
                body = locate("body_text.parquet")
            reader = db.execute(PARTITION, [body, shard + "00" * 31, shard + "ff" * 31, shard]).to_arrow_reader(8)
            rows = 0
            with pq.ParquetWriter(tmp, reader.schema, compression="zstd", compression_level=3) as writer:
                for batch in reader:
                    writer.write_batch(batch)
                    rows += batch.num_rows
            if rows != expected:
                raise ValueError(f"Partition {shard} produced {rows} of {expected} document identities")
            with tmp.open("rb") as completed:
                os.fsync(completed.fileno())
            os.replace(tmp, target)
    directory = os.open(output, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return total


def committee_vocabulary(directory, prepared):
    if directory is None:
        return {}
    # Project only the committee IDs already present in these immutable shards.
    with closing(duckdb.connect(config={"threads": 1})) as db:
        active = {key for key, in db.execute("SELECT DISTINCT unnest(committee_keys) FROM read_parquet(?)",
                                             [str(prepared / "*.parquet")]).fetchall()}
    columns = ["system_code", "chamber", "name", "names"]
    labels, aliases = {}, {}
    for row in pq.read_table(directory, columns=columns).to_pylist():
        key = row["system_code"]
        if key not in active:
            continue
        # The archive orders official names most recent first, including for retired committees.
        history = [entry["name"] for entry in row["names"] or [] if entry["name"]]
        name = history[0] if history else row["name"]
        if not name or name.casefold() == key.casefold():
            continue
        chamber = (row["chamber"] or "").title()
        label = f"{chamber} {name}" if chamber and not name.casefold().startswith(chamber.casefold() + " ") else name
        if key in labels:
            raise ValueError(f"Duplicate committee directory entry: {key}")
        labels[key] = label
        alternatives = list(dict.fromkeys(n for n in [row["name"], *history] if n and n.casefold() not in label.casefold()))
        if alternatives:
            aliases[key] = alternatives
    # Some distinct archive IDs share even the same chamber and formal name.
    counts = Counter(labels.values())
    for key, label in labels.items():
        if counts[label] > 1:
            labels[key] = f"{label} ({key})"
    return {"facet_labels": {"committee_keys": labels},
            "facet_aliases": {"committee_keys": aliases}}


def prepare(origin, work, pin, local):
    ready = work / "prepared.json"
    result = json.loads(ready.read_text()) if ready.is_file() else {}
    if "committee_vocabulary" not in result:
        locate = source_files(origin, work, pin, local)
        if "records" not in result:
            result["records"] = prepare_documents(work, locate)
        result["committee_vocabulary"] = committee_vocabulary(locate("committees.parquet"), work / "prepared")
        save(ready, result)
    return result


def filter_vocabulary(committees):
    terms = json.loads(files("congress_shared").joinpath("data/document-classifications.json").read_text(encoding="utf-8"))
    kinds = terms["kinds"]
    families = {key: entry if entry is not None else kinds[key] for key, entry in terms["families"].items()}
    groups = {"document_family": families, "document_kind": kinds}
    labels = dict(committees.get("facet_labels", {}))
    labels["chambers"] = {"house": "House", "senate": "Senate", "joint": "Joint"}
    descriptions = {
        "document_family": "A broad group of related document kinds. For example, Statement includes opening statements and witness testimony.",
        "document_kind": "A specific type assigned to a document, such as Opening Statement or Witness Testimony. A record can have more than one kind.",
    }
    help_text = {}
    for field, entries in groups.items():
        labels[field] = {key: entry["label"] for key, entry in entries.items()}
        help_text[field] = {"description": descriptions[field],
                            "values": {key: entry["description"] for key, entry in entries.items()}}
    return {**committees, "facet_labels": labels, "facet_help": help_text}


_COMPATIBLE_METADATA_KEYS = ("excerpt_key", "facet_labels", "facet_aliases", "facet_help")
_PASSAGE_MANIFEST_REQUIRED = frozenset({"release_id", "model", "dimensions", "passages", "documents", "parquet"})
_PASSAGE_MANIFEST_ALLOWED = _PASSAGE_MANIFEST_REQUIRED | {"config_version", "keyword_parquet", "layout"}
DEFAULT_SWAP_WARN_GIB = 2.0


def has_passage_keywords(passages):
    """Whether a passage attachment provides passage-level BM25 keyword ranking (dual or unified)."""
    return isinstance(passages, dict) and (
        passages.get("layout") == passage_keywords.LAYOUT_UNIFIED or bool(passages.get("keyword_parquet"))
    )


def read_swap_usage(meminfo=Path("/proc/meminfo")):
    """Read Linux swap totals from ``/proc/meminfo``; return None when unavailable."""
    path = Path(meminfo)
    if not path.is_file():
        return None
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("SwapTotal:", "SwapFree:"):
            try:
                values[parts[0][:-1]] = int(parts[1]) * 1024
            except ValueError:
                return None
    if "SwapTotal" not in values or "SwapFree" not in values:
        return None
    total, free = values["SwapTotal"], values["SwapFree"]
    return {"swap_total_bytes": total, "swap_free_bytes": free, "swap_used_bytes": max(0, total - free)}


def check_post_attach_swap(*, meminfo=Path("/proc/meminfo"), threshold_gib=DEFAULT_SWAP_WARN_GIB,
                           recycle_db=False, runner=None):
    """Warn on high post-attach swap usage and optionally recycle ``spicyengine-db.service``."""
    if threshold_gib <= 0:
        raise ValueError("Swap warning threshold must be positive")
    usage = read_swap_usage(meminfo)
    if usage is None:
        return None
    threshold_bytes = int(threshold_gib * (1024 ** 3))
    used = usage["swap_used_bytes"]
    warned = used > threshold_bytes
    recycled = False
    if warned:
        event = {
            "event": "spicyengine_post_attach_swap_high",
            "swap_used_mib": round(used / (1024 ** 2), 1),
            "swap_free_mib": round(usage["swap_free_bytes"] / (1024 ** 2), 1),
            "swap_total_mib": round(usage["swap_total_bytes"] / (1024 ** 2), 1),
            "threshold_gib": threshold_gib,
            "recycle_db": bool(recycle_db),
        }
        print(json.dumps(event, sort_keys=True), file=sys.stderr)
        if recycle_db:
            run = runner or subprocess.run
            run(["systemctl", "restart", "spicyengine-db.service"], check=True)
            run(["systemctl", "start", "spicyengine.service"], check=True)
            recycled = True
    return usage | {"warned": warned, "recycled": recycled}


def engine_status(engine):
    """Query the live SpicyEngine dataset status, returning None when no dataset is published yet."""
    proc = subprocess.run([engine, "status"], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        lowered = detail.lower()
        if "publish a dataset before searching" in lowered or "does not exist" in lowered:
            return None
        raise RuntimeError(f"Unable to inspect live SpicyEngine status before publish: {detail or proc.returncode}")
    try:
        status = json.loads(proc.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Live SpicyEngine status returned invalid JSON: {error}") from error
    if not isinstance(status, dict):
        raise RuntimeError("Live SpicyEngine status did not return a JSON object")
    return status


def would_drop_passages(live_status, definition):
    """Return True when publishing definition would drop currently attached passage embeddings."""
    if not live_status or not live_status.get("passages"):
        return False
    old_dataset = live_status.get("dataset")
    if not isinstance(old_dataset, dict):
        return True
    if old_dataset == definition:
        return False
    if old_dataset.get("release_id") != definition.get("release_id"):
        return True
    mask = dict.fromkeys(_COMPATIBLE_METADATA_KEYS)
    return (old_dataset | mask) != (definition | mask)


def load_passages_manifest(path, *, release_id, expected_documents):
    """Validate a passage attachment manifest before publishing a replacement dataset."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not (_PASSAGE_MANIFEST_REQUIRED <= set(raw) <= _PASSAGE_MANIFEST_ALLOWED):
        raise ValueError(
            "Passages manifest must define release_id, model, dimensions, passages, documents, and parquet"
        )
    if raw["release_id"] != release_id:
        raise ValueError(
            f"Passages manifest release_id {raw['release_id']!r} differs from target release {release_id!r}"
        )
    if type(raw["documents"]) is not int or raw["documents"] != expected_documents:
        raise ValueError(
            f"Passages manifest documents ({raw['documents']!r}) differs from prepared rows ({expected_documents})"
        )
    if type(raw["passages"]) is not int or raw["passages"] < 1:
        raise ValueError("Passages manifest must declare a positive passages count")
    if type(raw["dimensions"]) is not int or not 1 <= raw["dimensions"] <= 1024:
        raise ValueError("Passages manifest dimensions must be an integer between 1 and 1024")
    if not isinstance(raw["model"], str) or not raw["model"].strip():
        raise ValueError("Passages manifest model must be a non-empty string")
    layout = raw.get("layout", passage_keywords.LAYOUT_DUAL)
    if not isinstance(layout, str) or layout not in passage_keywords.LAYOUTS:
        raise ValueError("Passages manifest layout must be 'dual' or 'unified'")
    if layout == passage_keywords.LAYOUT_UNIFIED and "keyword_parquet" in raw:
        raise ValueError("Unified passage layout reads text from parquet and does not accept keyword_parquet")
    for key in ("parquet", "keyword_parquet"):
        if key in raw and (not isinstance(raw[key], str) or not raw[key].startswith("/")):
            raise ValueError(f"Passages manifest {key} must be an absolute mounted path")
    return raw


def sibling_passage_directory(manifest, name):
    """The sibling directory (e.g. ``keywords`` or ``unified``) for ``parquet`` = ``<serving>/*.parquet``."""
    pattern = Path(manifest["parquet"])
    if pattern.name != "*.parquet":
        raise ValueError(f"Building {name} passages requires a passages manifest parquet of <directory>/*.parquet")
    return pattern.parent, pattern.parent.parent / name


def keyword_directory(manifest):
    """The sibling ``keywords`` directory for a manifest whose ``parquet`` is ``<serving>/*.parquet``."""
    return sibling_passage_directory(manifest, "keywords")


def update(root, *, origin=ORIGIN, saved=None, local=None, engine=None, check_query=None,
           staged=False, prefer_staged=False, expected_release_id=None,
           allow_drop_passages=False, passages_manifest=None,
           ensure_keywords=False, previous_keywords=None, allow_drop_passage_keywords=False,
           unified_passages=False, previous_unified=None,
           recycle_db_if_swapped=False, swap_warn_gib=DEFAULT_SWAP_WARN_GIB):
    if ensure_keywords and unified_passages:
        raise ValueError("Cannot combine --ensure-keywords with --unified-passages")
    if (ensure_keywords or unified_passages) and passages_manifest is None:
        flag = "--unified-passages" if unified_passages else "--ensure-keywords"
        raise ValueError(f"{flag} requires --passages-manifest")
    if swap_warn_gib <= 0:
        raise ValueError("--swap-warn-gib must be positive")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pin = resolve(origin, saved, staged=staged, prefer_staged=prefer_staged,
                      expected_release_id=expected_release_id)
        release = pin["release_id"]
        version = Path(release) / pin["text"]["sha256"]
        legacy = root / "search-v1" / version
        work = legacy if (legacy / "prepared.json").is_file() else root / RECIPE / version
        work.mkdir(parents=True, exist_ok=True)
        if not (work / "pin.json").is_file():
            save(work / "pin.json", pin)
        ready = prepare(origin, work, pin, local)
        definition = {"input": {"parquet": str(work / "serving" / "*.parquet")}, "text_storage": "source",
                      "excerpt_key": "text_sha256",
                      "label": f"Congressional archive · {release[:12]}", "release_id": release,
                      **filter_vocabulary(ready["committee_vocabulary"]),
                      "fields": FIELDS | {"listed_on": "listed_on", "pdf_url": "pdf_url"}}
        if work == legacy:
            # A completed v1 release keeps its index and immutable shards, including on restore.
            links = work / "source-links.parquet"
            if not links.is_file():
                locate = source_files(origin, work, pin, local)
                temporary = links.with_suffix(".partial")
                with closing(duckdb.connect(config={"threads": 1})) as db:
                    load_documents(db, locate, include_meetings=False)
                    db.sql("""SELECT 'archive-documents:' || lower(hex(link_key)) AS id, listed_on, pdf_url
                              FROM documents WHERE listed_on IS NOT NULL OR pdf_url IS NOT NULL
                              ORDER BY id""").write_parquet(str(temporary), compression="zstd", row_group_size=2048)
                with temporary.open("rb") as complete:
                    os.fsync(complete.fileno())
                temporary.replace(links)
            definition.update(fields=FIELDS, source_links=str(links))
        # Once preparation commits, only the search partitions are needed locally.
        for name in ("body_text.parquet", "detail.parquet", "sources.parquet", "committees.parquet", "meetings.parquet"):
            (work / "downloads" / name).unlink(missing_ok=True)
        manifest = work / "dataset.json"
        if not manifest.exists() or json.loads(manifest.read_text()) != definition:
            save(manifest, definition)
        if engine:
            live_status = []

            def live():
                if not live_status:
                    live_status.append(engine_status(engine))
                return live_status[0]

            validated_passages = (
                load_passages_manifest(passages_manifest, release_id=release, expected_documents=ready["records"])
                if passages_manifest is not None
                else None
            )
            if validated_passages is not None and ensure_keywords:
                if validated_passages.get("layout") == passage_keywords.LAYOUT_UNIFIED:
                    raise ValueError("Cannot use --ensure-keywords with a layout='unified' passages manifest")
                # Build before publishing: a failed build must leave the live index and its passages intact.
                serving, keywords = keyword_directory(validated_passages)
                declared = validated_passages.get("keyword_parquet")
                if declared is not None and declared != str(keywords / "*.parquet"):
                    raise ValueError(f"Passages manifest keyword_parquet {declared!r} differs from {keywords}/*.parquet")
                if previous_keywords is None:
                    attached = ((live() or {}).get("passages") or {}).get("keyword_parquet")
                    previous_keywords = Path(attached).parent if attached else None
                passage_keywords.ensure_keywords(
                    serving, work / "prepared", keywords, release_id=release, previous=previous_keywords,
                    expected_passages=validated_passages["passages"], expected_documents=ready["records"])
                validated_passages = validated_passages | {"keyword_parquet": str(keywords / "*.parquet")}
            if validated_passages is not None and unified_passages:
                if validated_passages.get("layout") == passage_keywords.LAYOUT_UNIFIED:
                    raise ValueError(
                        "Cannot use --unified-passages with a manifest that already declares layout='unified'"
                    )
                # Build combined text + float16 vector shards before publishing so live passages stay intact on error.
                serving, unified = sibling_passage_directory(validated_passages, "unified")
                if previous_unified is None:
                    live_passages = (live() or {}).get("passages") or {}
                    if live_passages.get("layout") == passage_keywords.LAYOUT_UNIFIED and live_passages.get("parquet"):
                        previous_unified = Path(live_passages["parquet"]).parent
                passage_keywords.build_unified_passages(
                    serving, work / "prepared", unified, release_id=release,
                    dimensions=validated_passages["dimensions"], previous=previous_unified,
                    expected_passages=validated_passages["passages"], expected_documents=ready["records"])
                validated_passages = {
                    k: v for k, v in validated_passages.items() if k != "keyword_parquet"
                } | {"parquet": str(unified / "*.parquet"), "layout": passage_keywords.LAYOUT_UNIFIED}
            if (validated_passages is not None and not has_passage_keywords(validated_passages)
                    and not allow_drop_passage_keywords):
                live_passages = (live() or {}).get("passages")
                if has_passage_keywords(live_passages):
                    source = live_passages.get("keyword_parquet") or live_passages.get("parquet")
                    raise RuntimeError(
                        f"Refusing to attach vector-only passages to {release[:12]}: live SpicyEngine ranks passages "
                        f"by keyword from {source}. Pass --ensure-keywords or --unified-passages to preserve "
                        f"passage keyword ranking, or --allow-drop-passage-keywords to attach vectors only."
                    )
            if validated_passages is None and not allow_drop_passages:
                live_now = live()
                if would_drop_passages(live_now, definition):
                    attached = live_now["passages"]
                    live_release = attached.get("release_id") or (live_now.get("dataset") or {}).get("release_id")
                    raise RuntimeError(
                        f"Refusing to publish {release[:12]} without passages: live SpicyEngine currently has "
                        f"{attached.get('passages')} attached passages ({attached.get('model')}) on release "
                        f"{str(live_release)[:12]}. Pass --passages-manifest <path> to attach matching passages "
                        f"or --allow-drop-passages to publish full-text only."
                    )
            args = [engine, "publish", str(manifest), "--shards-from", str(work / "prepared"),
                    "--expected-rows", str(ready["records"])]
            if check_query:
                args.extend(["--check-query", check_query])
            if validated_passages is not None:
                published = subprocess.run(args, check=True, stdout=subprocess.PIPE, text=True)
                try:
                    config = json.loads(published.stdout)
                except json.JSONDecodeError as error:
                    raise RuntimeError(f"SpicyEngine publish did not return JSON config: {error}") from error
                revision = config.get("revision") if isinstance(config, dict) else None
                if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{64}", revision):
                    raise RuntimeError("SpicyEngine publish output did not include a 64-hex revision")
                stamped = work / "passages-attach.json"
                save(stamped, validated_passages | {"config_version": revision})
                subprocess.run([engine, "attach-passages", str(stamped)], check=True)
                check_post_attach_swap(threshold_gib=swap_warn_gib, recycle_db=recycle_db_if_swapped)
            else:
                subprocess.run(args, check=True)
        return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pin", type=Path, help="Replay a saved pin.json, including after the upstream pointer moves")
    parser.add_argument("--source-dir", type=Path, help="Reuse matching local detail, sources and body_text Parquet")
    parser.add_argument("--engine", help="Installed spicyengine executable; omit to prepare only")
    parser.add_argument("--check-query", help="Search to verify before activating a new index")
    parser.add_argument("--staged", action="store_true", help="Resolve staged candidate pointers ahead of the live flip")
    parser.add_argument("--prefer-staged", action="store_true", help="Prefer active staged candidate pointers, else live")
    parser.add_argument("--release-id", help="Require this exact 64-hex release ID")
    parser.add_argument("--allow-drop-passages", action="store_true",
                        help="Permit publishing a replacement index even when live SpicyEngine has attached passages")
    parser.add_argument("--passages-manifest", type=Path,
                        help="Attach matching passage embeddings immediately after publishing (stamps config_version)")
    parser.add_argument("--ensure-keywords", action="store_true",
                        help="Build and verify keyword passages in the sibling keywords/ directory before publishing")
    parser.add_argument("--previous-keywords", type=Path,
                        help="Hard-link unchanged files from this keyword directory (default: the live one)")
    parser.add_argument("--unified-passages", action="store_true",
                        help="Build combined text+float16-vector Parquet in sibling unified/ and attach layout='unified'")
    parser.add_argument("--previous-unified", type=Path,
                        help="Hard-link unchanged files from this unified directory (default: live unified dir)")
    parser.add_argument("--allow-drop-passage-keywords", action="store_true",
                        help="Permit attaching vector-only passages when live SpicyEngine ranks passages by keyword")
    parser.add_argument("--recycle-db-if-swapped", action="store_true",
                        help="Restart spicyengine-db.service after attach-passages if swap usage exceeds --swap-warn-gib "
                             "(requires root/systemctl privileges)")
    parser.add_argument("--swap-warn-gib", type=float, default=DEFAULT_SWAP_WARN_GIB,
                        help=f"Warn (or recycle with --recycle-db-if-swapped) when post-attach swap exceeds this GiB "
                             f"(default: {DEFAULT_SWAP_WARN_GIB})")
    args = parser.parse_args()
    if args.ensure_keywords and args.unified_passages:
        parser.error("Cannot combine --ensure-keywords with --unified-passages")
    if (args.ensure_keywords or args.unified_passages) and args.passages_manifest is None:
        parser.error("--ensure-keywords and --unified-passages require --passages-manifest")
    if args.swap_warn_gib <= 0:
        parser.error("--swap-warn-gib must be positive")
    print(update(args.root, saved=args.pin, local=args.source_dir, engine=args.engine,
                 check_query=args.check_query, staged=args.staged, prefer_staged=args.prefer_staged,
                 expected_release_id=args.release_id, allow_drop_passages=args.allow_drop_passages,
                 passages_manifest=args.passages_manifest, ensure_keywords=args.ensure_keywords,
                 previous_keywords=args.previous_keywords,
                 allow_drop_passage_keywords=args.allow_drop_passage_keywords,
                 unified_passages=args.unified_passages, previous_unified=args.previous_unified,
                 recycle_db_if_swapped=args.recycle_db_if_swapped, swap_warn_gib=args.swap_warn_gib))


if __name__ == "__main__":
    main()

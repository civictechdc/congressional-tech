# Metadata typing and keys: final review and decisions

Reviewed: house-naming 3.2.7 output on 50,000 random (filename, source URL) pairs from the
Oct 19 catalog, and URL patterns over all 1,026,659 documents with a source URL. Scripts are in
this session's scratchpad: `hn_keys.py`, `url_keys.py`.

## Field profile (house-naming `metadata`, 50k files, 215 distinct fields)

Fields that are real identifiers or typed facts:

| Field | Files | Multi-valued | Shape |
|---|---:|---:|---|
| `congress` | 34.7% | 0% | 100% integer |
| `committee_code` | 16.9% | 3.0% | House codes (`AG00`) |
| `meeting_date` | 16.0% | 0% | 100% `YYYYMMDD` |
| `date_token_candidates` | 19.0% | 1.4% (ambiguous dates) | ISO dates |
| `publication_type` / `publication_number` | 14.2% | 0% | GPO ids (`hhrg` + `57329`) |
| `measure_type`, `measure_number`, `measure_references` | 2.3–3.8% | ≤ 0.8% | `hr` + digits; references like `hr4009` |
| `bioguide_token`, `sponsor_bioguide_id` | 2.6%, 1.6% | 0% | Bioguide IDs (`A000370`) |
| `revision_number` | 1.0% | 0% | integer (`-U1` suffixes) |

Not keys: `witness_id` (name fragments such as `SmithJ`), `generic_identifier` (ambiguous
numbers, 4.9% multi-valued), `vote_id`, and `amendment_id` (meaningful only with a measure).

## URL-derived identifiers (all documents)

| Pattern | Documents | Distinct |
|---|---:|---:|
| `docs.house.gov/meetings/<C>/<SC>/<YYYYMMDD>/<eventId>/` | 45,761 | 6,551 events |
| `congress.gov/<n>/meeting/<chamber>/<eventId>/` | 142,997 | 11,634 meetings |
| `govinfo.gov/(content/pkg\|app/details)/<packageId>` | 141,694 | 36,943 packages |
| congress.gov bill or amendment pages | 334 | — |

House event IDs and Congress.gov House meeting IDs share one ID space: 4,715 of 6,550 House
event IDs also appear as Congress.gov meeting IDs. That is the committee-meeting `eventId` the
committee explorer already uses.

## Decisions (owner, 2026-10-24)

1. **Meeting key.** `meeting_ref struct<chamber string, event_id int64>` per source file,
   computed in the model SQL:
   - from the source URL (both patterns above);
   - else from the linking page in `page_links` when the parent is a meeting page;
   - else from House meeting XML document lists.

   Documents take the set of their members' refs. This enables "all documents for this hearing"
   and joins to the committee explorer's meetings. Nothing new is stored in the lake (it is
   derivable, like `url_key`).
2. **Document date.** `document_date date32`, from `meeting_date`, else a single
   `date_token_candidates` value, else null (never a guess among ambiguous candidates). Native
   in `filename_readings`, carried to `documents` and to `list.parquet` (dictionary-encoded,
   well under 1 MB). Readers sort and filter by hearing or document date; `first_captured`
   stays separate.
3. **Official record keys** as typed `detail` fields, composed in the model:
   - `govinfo_package_id string` (URL, else a GPO-pattern filename stem);
   - `measure_keys list<string>` as `{congress}-{type}-{number}` (from `measure_*`,
     `measure_references` and `congress`);
   - `bioguide_ids list<string>` (`bioguide_token`, `sponsor_bioguide_id`).

   Pages link out to the GPO record, the bill and the member. There are no lake changes.

The literal house-naming strings stay in the `fields` fold unchanged; the typed values exist
only in the composed keys and `document_date`, preserving house-naming's literal-source
contract.

## Extras considered (owner, 2026-10-24)

**Adopted: committee names.**
- `committee_key` is the Congress.gov committee `systemCode` derived from house-naming's
  `committee_code`. For House codes it is `'hs' || lower(code)`, so `AG03` becomes `hsag03`.
- Names are joined on `(congress, committee_key)` to the committee records
  `acquisition/committees.py` already collects (keyed `{congress}|{systemCode}`), falling back
  to the most recent congress's name when the document's congress has no record.
- `list` facets and `detail` show the name; the code stays in the fold.
- E1 reports unmapped codes with counts.

This matches the committee explorer's committee filters.

**Considered, not chosen for now:**
- Original-link status: 36,137 documents' source URLs last returned 404 or 410, 865k returned
  2xx, and 338k were never checked.
- Saved-file size: 15,293 saved files are over 10 MB, 3,042 over 50 MB and 263 over 200 MB;
  the largest is 1.19 GB.
- Witness links from House meeting XML.

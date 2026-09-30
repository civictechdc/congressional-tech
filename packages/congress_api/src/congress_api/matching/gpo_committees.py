"""Reconcile GPO committee claims and additive cached metadata."""

import collections
import json
import re

from congress_api.matching.reviewed_committees import reviewed
from congress_api.parsers.gpo_hearings import SMALL_WORDS


def merge_cached_row(old, parsed, *, live_refresh=False):
    """Combine explicit facts without replacing existing scalar corrections.

    Only a current network response may fill legacy scalar blanks: an offline
    cache can predate both a source correction and a deliberately cleared value.
    """
    merged = dict(old)
    if live_refresh:
        for field in ('event_id', 'committee_code_gpo', 'committee_name', 'subcommittees',
                      'title', 'held_date', 'date_ingested', 'serial', 'html_url', 'pdf_url'):
            merged[field] = old.get(field) or parsed.get(field, '')
        if parsed.get('record_type') == 'errata':
            merged['record_type'] = 'errata'
    for field in ('html_urls', 'pdf_urls', 'committee_codes_gpo', 'committee_codes',
                  'serial_numbers', 'granule_classes', 'held_dates'):
        values = str(old.get(field) or '').split(';')
        singular = {'html_urls': 'html_url', 'pdf_urls': 'pdf_url',
                    'committee_codes_gpo': 'committee_code_gpo', 'committee_codes': 'committee_code'}.get(field)
        if singular and old.get(singular):
            values.insert(0, old[singular])
        merged[field] = ';'.join(dict.fromkeys(v for v in values + str(parsed.get(field) or '').split(';') if v))
    for field in ('document_class', 'preferred_citation'):
        merged[field] = old.get(field) or parsed[field]
    claims = json.loads(old.get('committee_metadata') or '[]')
    for claim in json.loads(parsed.get('committee_metadata') or '[]'):
        if claim not in claims:
            claims.append(claim)
    merged['committee_metadata'] = json.dumps(claims, ensure_ascii=False, separators=(',', ':')) if claims else ''
    files = json.loads(parsed.get('file_metadata') or '{}')
    for url, existing in json.loads(old.get('file_metadata') or '{}').items():
        files[url] = {**files.get(url, {}), **existing}
    merged['file_metadata'] = json.dumps(files, ensure_ascii=False, separators=(',', ':')) if files else ''
    # A cached MODS file can predate this row. Parser freshness belongs to a
    # successful network refresh, not additive replay of an unknown acquisition.
    return merged


VALID_CODE = re.compile(r"^[hsj][a-z0-9]{3}\d\d$")


def name_key(chamber: str, committee_name: str) -> tuple:
    """A committee's name reduced to its distinctive words, with its chamber: both chambers have a
    "Committee on the Judiciary"."""
    words = re.sub(r"[^a-z ]", " ", committee_name.lower()).split()
    return chamber, " ".join(w for w in words if w not in SMALL_WORDS and w not in ("committee", "united", "states", "senate", "house"))


def clean_rows(rows: dict[str, dict]) -> None:
    """Fix committee codes and flag errata, in place. Idempotent: always starts from GPO's own code."""
    for row in rows.values():
        if not row.get("committee_code_gpo") and "committee_code_gpo" not in row:
            row["committee_code_gpo"] = row["committee_code"]  # rows written before this column existed
        row.setdefault("record_type", "errata" if "[ERRATA]" in row["title"].upper() else "hearing")
        row.setdefault("hearing_dates", "")
        row.setdefault("text_read", "")

    def fix(code):
        code = (code or "").strip().lower()
        if len(code) == 6 and not VALID_CODE.match(code):
            code = code[:4] + code[4:].replace("o", "0")  # e.g. "hssmoo" -> "hssm00"
        return code if VALID_CODE.match(code) else ""

    ## for blank or unusable codes, use the code GPO most often gives that committee name in that chamber,
    ##  or in any chamber when only one has a committee of that name (a joint print of a Senate committee)
    by_name = collections.defaultdict(collections.Counter)
    for row in rows.values():
        code = fix(row["committee_code_gpo"])
        if code and row["committee_name"]:
            by_name[name_key(row["chamber"], row["committee_name"])][code] += 1
            by_name[name_key("", row["committee_name"])][code] += 1
    for row in rows.values():
        code = fix(row["committee_code_gpo"])
        if not code and row["committee_name"]:
            here, anywhere = by_name.get(name_key(row["chamber"], row["committee_name"])), by_name.get(name_key("", row["committee_name"]), {})
            code = here.most_common(1)[0][0] if here else next(iter(anywhere)) if len(anywhere) == 1 else ""
        codes = list(dict.fromkeys(fix(c) for c in row.get('committee_codes_gpo', '').split(';') if fix(c)))
        if code and code not in codes:
            codes.insert(0, code)
        decision = reviewed(row)
        if decision and decision.get('committee_codes') and not fix(row['committee_code_gpo']) and not row.get('committee_codes_gpo'):
            codes = decision['committee_codes']
        row["committee_code"] = codes[0] if codes else ""
        # An old cache row remains readable without asserting additional codes.
        if row.get('committee_codes_gpo') or (decision and decision.get('committee_codes')):
            row['committee_codes'] = ';'.join(codes)

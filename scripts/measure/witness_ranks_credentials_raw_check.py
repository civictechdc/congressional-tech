"""Judge extracted witness military ranks and credentials against raw source payloads (ct-17op).

    witness_ranks_credentials_raw_check.py --before GEN.parquet --after GEN.parquet --raw-root BODIES
        [--receipts-root RECEIPTS] --output OUT.json [--plant KIND ...]

Owner decision 2026-11-10 (recorded on ct-wy4c and ct-17op): military rank and academic, licensure,
fellowship, religious-order, or service-retirement credentials belong in their own fields (`rank`,
`credentials`), verbatim as printed (normalized spacing only), neither left in `name` nor dropped.

This check reads `--before` and `--after` `appearance_records` generations across all four sources
(`mods`, `senate_page`, `house_xml`, `congress_gov`) and inspects raw source bytes from `--raw-root`
(`<sha[:2]>/<sha>.gz`) and optional inline Congress.gov JSONL receipts in `--receipts-root` without
importing any parser or producer rule.

Both directions, per occurrence `(source, record_sha, source_locator)`; every flag fails the check:
- `removed`: an occurrence present in `--before` and absent in `--after` (`0` removals required).
- `rank_not_in_raw`: a non-empty `rank` whose printed text does not appear in the raw source payload.
- `civil_title_in_rank`: a civil, legislative, or clerical honorific (`Mr.`, `Dr.`, `The Honorable`,
  `Senator`, `Representative`, `Ambassador`, `Governor`, `Mayor`, `Rev.`, etc.) placed in `rank`.
- `credential_not_in_raw`: a non-empty `credentials` item whose printed tokens do not appear in the
  raw source payload.
- `suffix_in_credentials`: a generational suffix (`Jr.`, `Sr.`, `II`, `III`, `IV`) or corporate role
  (`CEO`, `CFO`, `COO`) placed in `credentials`.
- `rank_in_name`: an `after` witness `name` that still opens with a military rank prefix.
- `credential_in_name`: an `after` witness `name` that still holds a post-nominal degree, branch, or
  retirement credential.
- `credential_dropped`: an `after` witness row with empty `credentials` whose raw witness entry
  attaches an explicit degree or retirement post-nominal (`Ph.D.`, `M.D.`, `J.D.`, `(Ret.)`, etc.)
  to that witness's name and no sibling row of the same entry carries it.

`--plant` injects one wrong value on the `after` side per requested kind (`rank-in-name`,
`credential-dropped`, `ungrounded-rank`, `ungrounded-credential`), each on a distinct record, and
verifies the corresponding flag fires.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
from hashlib import sha256
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

SOURCES = ("mods", "senate_page", "house_xml", "congress_gov")

FLAGS = (
    "removed",
    "rank_not_in_raw",
    "civil_title_in_rank",
    "credential_not_in_raw",
    "suffix_in_credentials",
    "rank_in_name",
    "credential_in_name",
    "credential_dropped",
)

PLANTS = {
    "rank-in-name": "rank_in_name",
    "credential-dropped": "credential_dropped",
    "ungrounded-rank": "rank_not_in_raw",
    "ungrounded-credential": "credential_not_in_raw",
}

CIVIL_ONLY = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor", "rev", "reverend",
    "pastor", "rabbi", "sister", "sir", "hon", "honorable", "the honorable", "the hon",
    "senator", "sen", "representative", "rep", "delegate", "congressman", "congresswoman",
    "ambassador", "amb", "governor", "gov", "mayor", "president", "sheriff", "detective",
    "officer", "chief", "chairman", "chairwoman", "chair",
}

FORBIDDEN_CREDENTIALS = {
    "jr", "sr", "ii", "iii", "iv", "ceo", "cfo", "coo", "cio", "cto", "evp", "svp",
}

# Abbreviated or multi-word military ranks unambiguously mark rank before 1+ capitalized name words.
ABBR_OR_MULTI_RANK_IN_NAME = re.compile(
    r"^(?:"
    r"Sergeant Major of the (?:Army|Marine Corps)"
    r"|Master Chief Petty Officer(?: of the Navy)?"
    r"|Chief Master Sergeant(?: of the (?:Air|Space) Force)?"
    r"|(?:Command |First )?Sergeant Major|(?:Chief |Senior )?Master Sergeant"
    r"|Senior Chief(?: Petty Officer)?|Chief Petty Officer|Petty Officer (?:First|Second|Third) Class"
    r"|Chief Warrant Officer(?: [2-5]| (?:Two|Three|Four|Five))?|Warrant Officer(?: 1)?"
    r"|Rear Admiral(?: \(?(?:Upper|Lower) Half\)?)?|Vice Admiral"
    r"|(?:Lieutenant|Major|Brigadier) General|Lieutenant (?:Colonel|Commander|Junior Grade)"
    r"|(?:First|Second) Lieutenant|(?:Gunnery|Technical|Staff|First) Sergeant|Sergeant First Class"
    r"|Lance Corporal|Private First Class|Senior Airman|Airman First Class"
    r"|(?:Rear|Vice) Adm\.?|(?:Lt|Maj|Brig)\.? Gen\.?|Lt\.? (?:Col|Cmdr)\.?|(?:1st|2nd) Lt\.?"
    r"|(?:Sgt\.? Maj|Master Sgt|Tech\.? Sgt|Staff Sgt|1st Sgt)\.?|CWO-?[2-5]|CW[2-5]"
    r"|Gen\.|GEN|LTG|MG|BG|LtGen|MajGen|BrigGen|BGen"
    r"|Adm\.|ADM|VADM|RADM|RDML"
    r"|Col\.|COL|LTC|LtCol"
    r"|Cmdr\.|CDR|LCDR"
    r"|Maj\.|MAJ|Capt\.|CAPT|CPT"
    r"|Lt\.|LT|1LT|2LT|LTJG|ENS"
    r"|Sgt\.|SGT|CSM|SGM|SgtMaj|MSG|MSgt|GySgt|TSgt|SSG|SSgt|SFC|1SG|CMSgt|SMSgt"
    r"|MCPO|SCPO|CPO|Cpl\.|CPL|LCpl|Spc\.|SPC|Pvt\.|PFC|SrA"
    r")\s+[A-Z]"
)

# Single-word English ranks ("Major", "General", "Captain") can also be given names on two-word names
# ("Major Garrett"); require at least two capitalized name words after them.
WORD_RANK_IN_NAME = re.compile(
    r"^(?:General|Admiral|Colonel|Commander|Major|Captain|Lieutenant|Ensign|Sergeant|Corporal"
    r"|Specialist|Seaman|Private)\s+[A-Z][\w'’.-]+\s+[A-Z]"
)

CREDENTIAL_IN_NAME = re.compile(
    r"(?:,\s*(?:"
    r"Ph\.?D\.?|M\.?D\.?|D\.?O\.?|J\.?D\.?|LL\.?[BM]\.?|Ed\.?D\.?|Psy\.?D\.?|Pharm\.?D\.?"
    r"|D\.?D\.?S\.?|D\.?M\.?D\.?|D\.?V\.?M\.?|V\.?M\.?D\.?|D\.?N\.?P\.?|M\.?P\.?H\.?|M\.?B\.?A\.?"
    r"|M\.?P\.?A\.?|M\.?S\.?W\.?|R\.?N\.?|C\.?P\.?A\.?|F\.?A\.?C\.?P\.?|F\.?A\.?C\.?S\.?|Esq\.?"
    r"|USAF|USMC|USCG|USSF|USPHS"
    r")(?:$|[\s,)])"
    r"|\s+(?:"
    r"Ph\.?D\.?|M\.?D\.?|D\.?O\.?|J\.?D\.?|LL\.?[BM]\.?|Ed\.?D\.?|Psy\.?D\.?|Pharm\.?D\.?"
    r"|D\.?D\.?S\.?|D\.?M\.?D\.?|D\.?V\.?M\.?|V\.?M\.?D\.?|D\.?N\.?P\.?|M\.?P\.?H\.?|M\.?B\.?A\.?"
    r"|M\.?P\.?A\.?|M\.?S\.?W\.?|R\.?N\.?|C\.?P\.?A\.?(?!\s+Firm\b)|F\.?A\.?C\.?P\.?|F\.?A\.?C\.?S\.?|Esq\.?"
    r"|USAF|USMC|USCG|USSF|USPHS"
    r")$"
    r"|(?:^|[\s,])[(\[](?:(?:USA|USN|USAF|USMC|USCG|(?:U\.S\.|United States)\s+(?:Army|Navy|Air Force|Marine Corps|Coast Guard)),?\s+)?"
    r"[Rr]et(?:ired)?\.?(?:,?\s+(?:USA|USN|USAF|USMC|USCG|(?:U\.S\.|United States)\s+(?:Army|Navy|Air Force|Marine Corps|Coast Guard)))?[)\]]"
    r")"
)

EXPLICIT_POSTNOMINAL = re.compile(
    r"(?:,\s*|\s+)(?:"
    r"(Ph\.?D|M\.?D|D\.?O|D\.?D\.?S|D\.?V\.?M|Ed\.?D|Psy\.?D|Pharm\.?D|J\.?D|LL\.?M|M\.?P\.?H)"
    r"(?:\.(?![A-Za-z])|(?![A-Za-z.]))(?!\s+(?:[Cc]andidate|[Ss]tudent)\b)"
    r"|(\((?:(?:USA|USN|USAF|USMC|USCG),?\s+[Rr]et(?:ired)?\.?|Ret(?:ired)?\.?)\))"
    r")(?=$|[,;\s.)])"
)


def norm_space(text: str | None) -> str:
    return " ".join((text or "").split())


def plain_key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()


def load_generation(path: Path, *, names_only: bool = False) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    cols = ["source", "record_sha", "appearances"] if names_only else ["source", "record_sha", "package_id", "event_id", "appearances"]
    present = [c for c in cols if c in pq.read_schema(path).names]
    for batch in pq.ParquetFile(path).iter_batches(batch_size=512, columns=present):
        for row in batch.to_pylist():
            src = row["source"]
            if src not in SOURCES:
                continue
            sha = row["record_sha"].hex() if isinstance(row["record_sha"], bytes) else str(row["record_sha"])
            if names_only:
                out[(src, sha)] = {
                    "appearances": {a["source_locator"]: a.get("name") for a in (row.get("appearances") or ())},
                }
            else:
                out[(src, sha)] = {
                    "package_id": row.get("package_id"),
                    "event_id": row.get("event_id"),
                    "appearances": {
                        a["source_locator"]: {
                            "name": a.get("name"),
                            "rank": a.get("rank"),
                            "credentials": a.get("credentials"),
                        }
                        for a in (row.get("appearances") or ())
                    },
                }
    return out


def index_inline_receipts(
    receipts_root: Path | None,
    needed_digests: set[str] | None = None,
) -> dict[str, str]:
    if not receipts_root or not receipts_root.is_dir():
        return {}
    if needed_digests is not None and not needed_digests:
        return {}
    indexed: dict[str, str] = {}
    for gz in sorted(receipts_root.rglob("*.jsonl.gz")):
        with gzip.open(gz, "rb") as fh:
            for raw_line in fh:
                line = raw_line.rstrip(b"\r\n")
                digest = sha256(line).hexdigest()
                if needed_digests is None or digest in needed_digests:
                    indexed[digest] = extract_raw_context("congress_gov", line)[0]
                    if needed_digests is not None and len(indexed) >= len(needed_digests):
                        return indexed
    return indexed


def read_raw_context(
    source: str,
    digest: str,
    raw_root: Path,
    inline_receipts: dict[str, str],
) -> tuple[str, dict[str, str]] | None:
    body_path = raw_root / digest[:2] / f"{digest}.gz"
    if body_path.is_file():
        return extract_raw_context(source, gzip.decompress(body_path.read_bytes()))
    if source == "congress_gov" and digest in inline_receipts:
        return inline_receipts[digest], {}
    return None


def extract_raw_context(source: str, payload: bytes) -> tuple[str, dict[str, str]]:
    """Return `(whole_text, per_locator_entry_text)` from raw source bytes."""
    per_locator: dict[str, str] = {}
    if source == "mods":
        root = ET.fromstring(payload)
        lines = [norm_space("".join(el.itertext())) for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "witness"]
        for idx, line in enumerate(lines, start=1):
            per_locator[f"mods:witness[{idx}]"] = line
        return "\n".join(lines), per_locator

    if source == "house_xml":
        root = ET.fromstring(payload)
        witness_els = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] in ("witness", "hearing-witness")]
        chunks = []
        for idx, el in enumerate(witness_els, start=1):
            txt = norm_space(" ".join(t.strip() for t in el.itertext() if t and t.strip()))
            chunks.append(txt)
            per_locator[f"house_xml:witness[{idx}]"] = txt
        whole = norm_space(" ".join(t.strip() for t in root.itertext() if t and t.strip()))
        return whole, per_locator

    if source == "senate_page":
        decoded = payload.decode("utf-8", errors="replace")
        no_comments = re.sub(r"<!--.*?-->", " ", decoded, flags=re.S)
        visible = norm_space(html.unescape(re.sub(r"<[^>]+>", " ", no_comments)))
        return visible, per_locator

    if source == "congress_gov":
        decoded = payload.decode("utf-8", errors="replace")
        try:
            obj = json.loads(decoded)
        except json.JSONDecodeError:
            return norm_space(decoded), per_locator
        strings: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str):
                strings.append(norm_space(node))

        walk(obj)
        return "\n".join(strings), per_locator

    return norm_space(payload.decode("utf-8", errors="replace")), per_locator


def tokens_present(value: str, raw_text: str) -> bool:
    """Every alphabetic or numeric token of `value` appears in `raw_text` (case-insensitive)."""
    hay_compact = re.sub(r"[^a-z0-9]+", " ", raw_text.lower())
    hay_words = set(hay_compact.split())
    hay_nospace = hay_compact.replace(" ", "")
    for part in [p.strip() for p in value.split(",") if p.strip()]:
        norm = norm_space(part)
        if norm.lower() in raw_text.lower():
            continue
        words = re.findall(r"[a-z0-9]+", norm.lower())
        if not words:
            continue
        joined = "".join(words)
        if all(w in hay_words for w in words) or joined in hay_nospace:
            continue
        return False
    return True


def entry_has_dropped_credential(name: str, entry_text: str) -> str | None:
    """Return an explicit post-nominal printed right after `name` (or surname-first) in `entry_text`."""
    if not name or not entry_text:
        return None
    parts = [w for w in re.split(r"\s+", name.strip()) if w]
    if not parts:
        return None
    family = parts[-1].rstrip(",.")
    patterns = [re.escape(name.strip())]
    if len(parts) >= 2:
        given = " ".join(parts[:-1])
        patterns.append(rf"{re.escape(family)},\s*(?:[A-Za-z.]+\s+)*{re.escape(given)}")
        patterns.append(rf"{re.escape(family)},\s*(?=(?:Ph\.?D|M\.?D|D\.?O|D\.?D\.?S|D\.?V\.?M|Ed\.?D|J\.?D|\())")
    for pat in patterns:
        for m in re.finditer(pat, entry_text):
            tail = entry_text[m.end() : m.end() + 40]
            post = EXPLICIT_POSTNOMINAL.match(tail)
            if post:
                return post.group(1) or post.group(2)
    return None


def apply_plant(
    kind: str,
    after: dict[tuple[str, str], dict],
    raw_root: Path,
    inline_receipts: dict[str, str],
    taken: set[tuple[str, str]],
) -> dict:
    for key in sorted(after):
        if key in taken:
            continue
        source, digest = key
        try:
            ctx = read_raw_context(source, digest, raw_root, inline_receipts)
        except ET.ParseError:
            continue
        if ctx is None:
            continue
        whole_text, per_locator = ctx
        apps = after[key]["appearances"]
        for locator, row in sorted(apps.items()):
            name = row.get("name") or ""
            rank = row.get("rank") or ""
            creds = row.get("credentials") or ""
            if kind == "rank-in-name" and name and rank:
                planted_name = f"{rank} {name}"
                if ABBR_OR_MULTI_RANK_IN_NAME.search(planted_name) or WORD_RANK_IN_NAME.search(planted_name):
                    apps[locator] = {**row, "name": planted_name, "rank": None}
                    return {
                        "kind": kind,
                        "source": source,
                        "record_sha": digest,
                        "locator": locator,
                        "planted": planted_name,
                    }
            elif kind == "credential-dropped" and name and creds:
                base_loc = locator.split("/")[0]
                siblings = [k for k in apps if k.split("/")[0] == base_loc]
                entry = per_locator.get(base_loc) or whole_text
                if len(siblings) == 1 and entry_has_dropped_credential(name, entry):
                    apps[locator] = {**row, "credentials": None}
                    return {
                        "kind": kind,
                        "source": source,
                        "record_sha": digest,
                        "locator": locator,
                        "planted": None,
                    }
            elif kind == "ungrounded-rank" and name and not rank and "admiral" not in whole_text.lower():
                apps[locator] = {**row, "rank": "Vice Admiral"}
                return {
                    "kind": kind,
                    "source": source,
                    "record_sha": digest,
                    "locator": locator,
                    "planted": "Vice Admiral",
                }
            elif kind == "ungrounded-credential" and name and not creds and "pharm" not in whole_text.lower():
                apps[locator] = {**row, "credentials": "Pharm.D."}
                return {
                    "kind": kind,
                    "source": source,
                    "record_sha": digest,
                    "locator": locator,
                    "planted": "Pharm.D.",
                }
    return {"kind": kind, "source": None, "record_sha": None, "locator": None, "planted": None}


def judge(
    before: dict[tuple[str, str], dict],
    after: dict[tuple[str, str], dict],
    raw_root: Path,
    inline_receipts: dict[str, str],
) -> tuple[dict, dict[str, list[dict]]]:
    out: dict[str, list[dict]] = {f: [] for f in (*FLAGS, "missing_raw")}
    counts_by_source: dict[str, dict[str, int]] = {
        s: {"records": 0, "occurrences": 0, "rank": 0, "credentials": 0, "removed": 0}
        for s in SOURCES
    }

    for key in sorted(before.keys() | after.keys()):
        source, digest = key
        old_apps = (before.get(key) or {}).get("appearances") or {}
        if key not in after:
            for loc in sorted(old_apps):
                counts_by_source[source]["removed"] += 1
                out["removed"].append({"source": source, "record_sha": digest, "locator": loc})
            continue

        new_rec = after[key]
        new_apps = new_rec["appearances"]
        counts_by_source[source]["records"] += 1

        for loc in sorted(old_apps.keys() - new_apps.keys()):
            counts_by_source[source]["removed"] += 1
            out["removed"].append({"source": source, "record_sha": digest, "locator": loc})

        try:
            ctx = read_raw_context(source, digest, raw_root, inline_receipts)
        except ET.ParseError as exc:
            out["missing_raw"].append({"source": source, "record_sha": digest, "error": type(exc).__name__})
            continue
        if ctx is None:
            out["missing_raw"].append({"source": source, "record_sha": digest})
            continue
        whole_text, per_locator = ctx

        by_base: dict[str, list[dict]] = {}
        for loc, row in new_apps.items():
            by_base.setdefault(loc.split("/")[0], []).append(row)

        for loc, row in sorted(new_apps.items()):
            counts_by_source[source]["occurrences"] += 1
            name = norm_space(row.get("name"))
            rank = norm_space(row.get("rank"))
            creds = norm_space(row.get("credentials"))
            base_loc = loc.split("/")[0]
            entry_text = per_locator.get(base_loc) or whole_text
            meta = {
                "source": source,
                "record_sha": digest,
                "package_id": new_rec.get("package_id"),
                "event_id": new_rec.get("event_id"),
                "locator": loc,
                "name": name or None,
                "rank": rank or None,
                "credentials": creds or None,
            }

            if rank:
                counts_by_source[source]["rank"] += 1
                if plain_key(rank) in CIVIL_ONLY:
                    out["civil_title_in_rank"].append(meta)
                if not tokens_present(rank, entry_text) and not tokens_present(rank, whole_text):
                    out["rank_not_in_raw"].append(meta)

            if creds:
                counts_by_source[source]["credentials"] += 1
                items = [c.strip() for c in creds.split(",") if c.strip()]
                if any(plain_key(item) in FORBIDDEN_CREDENTIALS for item in items):
                    out["suffix_in_credentials"].append(meta)
                if not tokens_present(creds, entry_text) and not tokens_present(creds, whole_text):
                    out["credential_not_in_raw"].append(meta)

            if name:
                if ABBR_OR_MULTI_RANK_IN_NAME.search(name) or WORD_RANK_IN_NAME.search(name):
                    out["rank_in_name"].append(meta)
                if CREDENTIAL_IN_NAME.search(name):
                    out["credential_in_name"].append(meta)
                if not creds:
                    siblings_have_creds = any(norm_space(s.get("credentials")) for s in by_base.get(base_loc, ()))
                    if not siblings_have_creds:
                        check_scope = per_locator.get(base_loc)
                        if check_scope is None and source == "congress_gov":
                            old_val = old_apps.get(loc)
                            old_name = norm_space(old_val.get("name") if isinstance(old_val, dict) else old_val)
                            check_scope = old_name if old_name else None
                        if check_scope:
                            dropped = entry_has_dropped_credential(name, check_scope)
                            if dropped:
                                out["credential_dropped"].append({**meta, "dropped": dropped, "raw_entry": check_scope})

    totals = Counter()
    for s_counts in counts_by_source.values():
        for k, v in s_counts.items():
            totals[k] += v
    summary = {"by_source": counts_by_source, "totals": dict(totals)}
    return summary, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--receipts-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plant", nargs="+", choices=sorted(PLANTS), default=[])
    args = parser.parse_args(argv)

    before = load_generation(args.before, names_only=True)
    after = load_generation(args.after)
    needed_cgov = {
        sha
        for src, sha in after
        if src == "congress_gov" and not (args.raw_root / sha[:2] / f"{sha}.gz").is_file()
    }
    inline_receipts = index_inline_receipts(args.receipts_root, needed_digests=needed_cgov)

    planted = []
    taken: set[tuple[str, str]] = set()
    for kind in args.plant:
        p = apply_plant(kind, after, args.raw_root, inline_receipts, taken)
        if p.get("record_sha"):
            taken.add((p["source"], p["record_sha"]))
        planted.append(p)

    counts, out = judge(before, after, args.raw_root, inline_receipts)
    failed = {flag: len(out[flag]) for flag in FLAGS if out[flag]}
    for p in planted:
        target_flag = PLANTS[p["kind"]]
        p["flagged"] = (
            any(
                i["source"] == p["source"] and i["record_sha"] == p["record_sha"] and i["locator"] == p["locator"]
                for i in out[target_flag]
            )
            if p.get("record_sha")
            else None
        )

    result = {
        "status": "failed" if failed else "passed",
        "failed": failed,
        "counts": counts,
        "sizes": {k: len(v) for k, v in out.items()},
        "planted": planted,
        **out,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"status": result["status"], "failed": failed, "counts": counts, "planted": planted}))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

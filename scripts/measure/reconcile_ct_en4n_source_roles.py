"""Verify source roles, capture history, recovery and public exposure on the November 20 release."""

from collections import Counter, defaultdict
from hashlib import sha256
import gzip
from pathlib import Path
from zipfile import ZipFile

import pyarrow as pa
from viewer_publication.lookup_aliases import address_keys, lookup_form

from pdf_source_evidence import (
    BUCKET,
    EXPORT,
    INVENTORY,
    OCR,
    OUT,
    RELEASE,
    SELECTION,
    SSOT,
    archive_arg,
    fingerprint,
    lines,
    load,
    remote,
    require,
    selection,
    write,
)
from pdf_source_structure import zero_page_rows
from pdf_source_release import exposure, query, release_db, serializable

ASSESSMENT = OCR / "repairs/corpus-assessment-20261113"
OLD = Path("ticket-fixes-20261117/inventory/post-capture-append/invalid-sources.jsonl")
PROPOSAL = OCR / "repairs/response-roles-offline-20261113/deferred-source-proposal.json"
VIEWERS = ASSESSMENT / "triage-current-20261114/ct-g4yz-fallback-release-binding-20261115/binding.json"
EMPTY = sha256(b"").hexdigest()
ZIP = "c8feae38bafd625e3079a390436698a3453156a707018470ea006031b43280e4"


def source_bucket(item, provenance):
    category = item["failure_category"]
    if category != "error_response":
        return category
    if provenance:
        return {
            "embedded_house_meeting_fallback": item["failure_reason"],
            "retained_senate_listing_security_response": "senate_listing_security_response",
        }[provenance["kind"]]
    if item["failure_reason"] == "object-storage-no-such-key":
        require(all(u.endswith(".m3u8") for u in item["source_urls"]), "unexpected storage-error target role")
        return "missing_recording_playlist"
    if "natural_resources_not_found" in item["failure_reason"]:
        return "publisher_html_error_at_pdf_target"
    return "other_reviewed_html_error_response"


def url_exposure(db, urls):
    db.register("addresses", pa.table({"address": sorted(urls)}))
    table = [
        dict(
            address=u,
            lookup_key=bytes.fromhex(k),
            exact=k == sha256(("lookup:" + lookup_form(u)).encode()).hexdigest()[:16],
        )
        for u in sorted(urls)
        for k in sorted(address_keys(u)["lookup_key"])
    ]
    db.register("lookup_keys", pa.Table.from_pylist(table))
    result = {url: dict(sources=[], lookup=[], state=[], captures=[]) for url in urls}
    checks = {
        "sources": """SELECT a.address,d.*,s.url,s.member_path,s.is_saved,s.ordinal FROM addresses a
                     JOIN sources s ON a.address=s.url JOIN docs d USING(list_row) ORDER BY address,list_row,ordinal""",
        "lookup": """WITH hits AS (SELECT k.address,k.exact,u.list_row FROM lookup_keys k JOIN urls u USING(lookup_key))
                    SELECT h.address,d.*,h.exact FROM hits h JOIN docs d USING(list_row)
                    QUALIFY h.exact OR NOT bool_or(h.exact) OVER(PARTITION BY address) ORDER BY address,list_row""",
        "state": """SELECT a.address,s.attempts,s.last_attempt,s.last_status,s.last_outcome,s.last_good_at,
                   s.capture_disposition,s.capture_reason,s.capture_decision_id FROM addresses a JOIN url_state s
                   ON s.requested_url=a.address ORDER BY address""",
        "captures": """SELECT DISTINCT a.address,h.* FROM history h JOIN addresses a
                      ON a.address IN(h.requested_url,h.url,h.original_url,h.recovered_url)
                      ORDER BY address,receipt_key,receipt_line,capture_index""",
    }
    for field, sql in checks.items():
        for r in query(db, sql):
            result[r.pop("address")][field].append(serializable(r))
    return result


def controls(root):
    reviewed = ASSESSMENT / "response-examples-20261114/examples.jsonl"
    positive = {}
    for r in lines(root / reviewed):
        review = r["direct_source_review"]
        if review and review["case_id"] in ("M003", "M005"):
            require(fingerprint(Path(review["source_path"])) == r["body_sha256"], "reviewed source hash")
            positive[r["body_sha256"]] = dict(role=review["verdict"], evidence=str(reviewed))
    # Verify the actual container directory and member CRCs on an unhidden saved ZIP.
    path = root / OUT / (ZIP + ".zip")
    if not path.exists():
        client, _ = remote(root)
        key = f"bodies/sha256/{ZIP[:2]}/{ZIP}.gz"
        data = gzip.decompress(client.get_object(Bucket=BUCKET, Key=key)["Body"].read())
        require(sha256(data).hexdigest() == ZIP, "ZIP body identity")
        path.write_bytes(data)
    require(fingerprint(path) == ZIP, "cached ZIP SHA")
    with ZipFile(path) as z:
        require(z.namelist() and z.testzip() is None, "ZIP member validation")
        positive[ZIP] = dict(role="legitimate_zip_container", members=z.namelist(), evidence=path.name)
    feed_path = OCR / "repairs/house-floor-feed-20261113/shared-result.json"
    feed = load(root / feed_path)
    require(feed["entries"] == feed["unique_entry_ids"] == 2226, "complete House feed control")
    positive[feed["source_sha256"].split(":")[1]] = dict(role="atom_feed", evidence=str(feed_path))
    empty_path = (
        OCR / "repairs/accepted-text-adoption-20261114/accepted-set-v11/known-valid-empty-bodies.json"
    )
    for sha in load(root / empty_path):
        positive[sha] = dict(role="reviewed_valid_empty_reading", evidence=str(empty_path))
    phrases = Path("investigations/text-quantity-review-20261113/error-review-notes.jsonl")
    for r in lines(root / phrases):
        if r["classification"] == "ordinary-document-mentions-error-related-words":
            positive[r["body_sha256"]] = dict(
                role="ordinary_document_quoting_error_language",
                evidence=str(phrases),
                review_id=r["review_id"],
            )
    for r in load(root / VIEWERS)["rows"]:
        if r["pdf"]:
            positive[r["wrapper"]["body_sha256"]] = dict(
                role="statute_viewer", evidence=str(VIEWERS), linked_pdf=r["pdf"]["body_sha256"]
            )
    return positive


def verify_partition(rows, expected, controls_by_sha):
    keys = [r["body_sha256"] for r in rows]
    require(
        len(keys) == len(set(keys)) == len(expected) and set(keys) == set(expected),
        "inventory identity partition",
    )
    for r in rows:
        sha = r["body_sha256"]
        require(r["bucket"] == expected[sha] and bool(r["bucket"]), f"{sha} classification")
        require(sha not in controls_by_sha, f"{sha} legitimate control classified as invalid")
        require(r["live"]["export"] is None, f"{sha} invalid original delivered as text")
    return Counter(r["bucket"] for r in rows)


def verify_control(sha, info, state, exclusions):
    role = info["role"]
    exclusion = exclusions.get(sha)
    expected_role = {"atom_feed": "feed", "statute_viewer": "wrapper"}.get(role)
    require((exclusion or {}).get("source_role") == expected_role, f"{sha} false-positive error exclusion")
    if role == "statute_viewer":
        require(exclusion and exclusion["source_role"] == "wrapper" and not state["export"], "viewer role")
    if role == "reviewed_valid_empty_reading" and state["documents"]:
        require(state["export"] and state["export"]["text_sha256"] == EMPTY, f"{sha} changed empty control")
    if role == "ordinary_document_quoting_error_language" and state["documents"]:
        require(state["export"] and not exclusion, f"{sha} quoted error lost")
    if role == "legitimate_zip_container":
        require(
            any(d["format"] == "zip" and not d["hidden"] for d in state["documents"]), "public ZIP control"
        )


def check_missed_errors(rows):
    hard = [r for r in rows if r["bucket"] == "missing_recording_playlist"]
    require(
        hard
        and all(
            any((c["http_status"] or 0) >= 400 for c in r["capture_history"])
            and not r["live"]["documents"]
            and not r["live"]["export"]
            for r in hard
        ),
        "HTTP failure control",
    )
    soft = [r for r in rows if r["bucket"] == "publisher_html_error_at_pdf_target"]
    require(
        soft
        and all(
            (r["exclusion"] or {}).get("source_role") == "error_response"
            and not r["live"]["export"]
            and any(c["http_status"] == 200 for c in r["capture_history"])
            for r in soft
        ),
        "soft HTML error control",
    )


def public_copy_control(rows):
    """A public copy fails this check even when text selection correctly refuses it."""
    links = [
        dict(body_sha256=r["body_sha256"], bucket=r["bucket"], **doc)
        for r in rows
        for doc in r["live"]["documents"]
        if not doc["hidden"]
    ]
    return dict(passed=not links, unhidden_saved_copies=links)


def reconcile(root):
    out = root / OUT
    inventory = list(lines(root / INVENTORY))
    old = list(lines(root / OLD))
    require(
        len(inventory) == len(old) == 455
        and {r["record_id"] for r in inventory} == {r["record_id"] for r in old},
        "historical inventory changed",
    )
    require(
        fingerprint(root / INVENTORY)
        == load(root / INVENTORY.parent / "manifest.json")["inventory"]["sha256"],
        "source inventory digest",
    )
    provenance = load(out / "receipt-provenance.json")
    require(
        {(r["record_id"], r["body_sha256"]) for r in old}
        == {(r["record_id"], r["body_sha256"]) for r in inventory},
        "successor body identity",
    )
    require(
        set(provenance) == {r["body_sha256"] for r in old if not r["targets"]} and len(provenance) == 188,
        "not every historical source has receipt provenance",
    )
    zeros = load(out / "zero-page-structure.json")
    require(
        {r["body_sha256"] for r in zeros} == zero_page_rows(root).keys()
        and len(zeros) == 345
        and all(r["bucket"].startswith(("incomplete_pdf_", "damaged_pdf_")) for r in zeros),
        "zero-page partition",
    )
    positive = controls(root)
    policy = selection()
    excluded = {r["body_sha256"]: r for r in policy["excluded_bodies"]}
    wrappers = {
        r["body_sha256"]: r
        for r in load(root / SSOT / "review_packets/warc_review_packet.json")["warc_excluded_envelopes"]
    }
    proposals = load(root / PROPOSAL)
    landings = proposals["unresolved"] + proposals["excluded_resolved"]
    urls = {u for r in inventory for u in r["source_urls"]} | {r["source_url"] for r in provenance.values()}
    for row in zeros:
        urls.update(
            c[field]
            for c in row["captures"]
            for field in ("requested_url", "url")
            if c[field] and lookup_form(c[field]) is not None
        )
    for r in landings:
        urls.update([r["source_url"], r["target_url"], r["target_url"].replace("&download=1", "?download=1")])
    db = release_db(root)
    addresses = url_exposure(db, urls)
    err = query(
        db,
        """SELECT DISTINCT lower(hex(r.body_sha)) sha FROM selected r JOIN detail d ON r.body_sha=d.saved_body
                       WHERE r.parser='pdf_text' AND r.status='error' ORDER BY sha""",
    )
    keys = (
        {r["body_sha256"] for r in inventory + zeros}
        | set(positive)
        | set(excluded)
        | {r["sha"] for r in err}
    )
    keys.update(r["linked_pdf"] for r in positive.values() if "linked_pdf" in r)
    for r in inventory:
        keys.update(r.get("duplicate_wrapper_body_sha256", []))
        keys.update(d["body_sha256"] for d in r["alternatives"] if d.get("body_sha256"))
        for field, name in [
            ("search_coverage", "body_sha256"),
            ("accepted_recovery_20261120", "recovered_body_sha256"),
        ]:
            if value := (r.get(field) or {}).get(name):
                keys.add(value)
    for r in landings:
        keys.add(r["source_body_sha256"])
        keys.update(r["selected_body_sha256s"])
    keys.update(c["body_sha256"] for u in urls for c in addresses[u]["captures"] if c["body_sha256"])
    live = exposure(db, keys)
    history = defaultdict(list)
    for r in query(db, "SELECT * FROM history ORDER BY receipt_key,receipt_line,capture_index"):
        history[r["body_sha256"]].append(serializable(r))
    for sha, fact in provenance.items():
        require(
            any(
                all(c[field] == fact[field] for field in ("receipt_key", "receipt_line", "capture_index"))
                for c in history[sha]
            ),
            "missing receipt in live capture snapshot",
        )
    for sha, info in positive.items():
        verify_control(sha, info, live[sha], excluded)
        if info.get("linked_pdf"):
            require(live[info["linked_pdf"]]["export"], "linked PDF missing in v13")
    require(not (set(positive) & {r["body_sha256"] for r in zeros}), "valid source in damaged-PDF set")
    rows = []
    for r in inventory:
        sha = r["body_sha256"]
        fact = provenance.get(sha)
        targets = r["source_urls"] or [fact["source_url"]]
        # The same empty body occurs at unrelated URLs. Keep this obligation scoped to Cornwell.
        captures = (
            history[sha]
            if sha != EMPTY
            else [c for c in addresses[targets[0]]["captures"] if c["body_sha256"] == sha]
        )
        row = dict(
            record_id=r["record_id"],
            body_sha256=sha,
            bucket=source_bucket(r, fact),
            reason=r["failure_reason"],
            failure_category=r["failure_category"],
            source_evidence=r["source_evidence"],
            source_review_scope=r.get("source_review_scope"),
            receipt_provenance=fact,
            capture_history=captures,
            addresses=targets,
            archive_wrapper_shas=r.get("duplicate_wrapper_body_sha256", []),
            live=live[sha],
            exclusion=excluded.get(sha),
            operational={
                k: r.get(k)
                for k in (
                    "recovery_open",
                    "recovery_state",
                    "needs_refetch",
                    "targets",
                    "next_action",
                    "search_coverage",
                    "accepted_recovery_20261120",
                    "alternatives",
                )
            },
        )
        if fact:
            row["capture_eligibility"] = (
                "Historical listing-page response. No missing document URL established by the receipt."
            )
        elif row["bucket"] == "missing_recording_playlist":
            row["capture_eligibility"] = (
                "Recording playlist target. Preserve recording recovery separately from document extraction."
            )
        else:
            row["capture_eligibility"] = "See per-target qualification and dated recovery decision."
        rows.append(row)
    counts = verify_partition(
        rows, {r["body_sha256"]: source_bucket(r, provenance.get(r["body_sha256"])) for r in old}, positive
    )
    require(sum(counts.values()) == 455, "source-role count")
    require(
        all(
            r["exclusion"] and r["exclusion"]["source_role"] == "error_response"
            for r in rows
            if r["failure_category"] == "error_response"
        ),
        "missing reviewed error exclusion",
    )
    keys_in_inventory = {r["body_sha256"] for r in rows}
    pdf_errors = []
    zero_by_sha = {r["body_sha256"]: r for r in zeros}
    for r in err:
        sha = r["sha"]
        require(not live[sha]["export"], "PDF error appears in text export")
        pdf_errors.append(
            dict(
                body_sha256=sha,
                in_inventory=sha in keys_in_inventory,
                historical_zero_page=sha in zero_by_sha,
                live=live[sha],
            )
        )
    require(
        len(pdf_errors) == load(out / "v13-pointer.json")["coverage"]["readings"]["pdf_text:error"] == 27,
        "selected error population",
    )
    require(all(live[s]["export"] is None for s in excluded), "reviewed exclusion leak")
    for r in zeros:
        sha = r["body_sha256"]
        require(not live[sha]["export"], "failed PDF in export")
        r.update(
            in_inventory=sha in keys_in_inventory,
            live=live[sha],
            addresses=sorted(
                {c[k] for c in r["captures"] for k in ("url", "requested_url") if c[k] in addresses}
            ),
        )
    for sha, r in wrappers.items():
        payload = r["payload_sha256"]
        require(
            sha in next(x["archive_wrapper_shas"] for x in rows if x["body_sha256"] == payload)
            and any(
                a["receipt_key"] == b["receipt_key"]
                and a["receipt_line"] == b["receipt_line"]
                and a["capture_index"] > 0
                and b["capture_index"] == 0
                for a in history[sha]
                for b in history[payload]
            ),
            "archive wrapper does not share payload receipt",
        )
    check_missed_errors(rows)
    truncated = [
        r
        for r in rows
        if r["failure_category"].startswith(("incomplete_pdf", "damaged_pdf", "pdf_truncated"))
    ]
    for r in truncated:
        require(
            not r["live"]["export"]
            and (
                not r["live"]["documents"]
                or any(rd["status"] == "error" and rd["parser"] == "pdf_text" for rd in r["live"]["readings"])
            ),
            "damaged PDF escaped the reading refusal",
        )
    specimen = next(
        r
        for r in truncated
        if r["body_sha256"] == "04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30"
    )
    require(not specimen["live"]["documents"], "truncated short-bill control still selected as saved copy")
    for r in landings:
        targets = [r["target_url"], r["target_url"].replace("&download=1", "?download=1")]
        bodies = set(r["selected_body_sha256s"]) | {
            c["body_sha256"] for u in targets for c in addresses[u]["captures"] if c["body_sha256"]
        }
        r["live_source"] = live[r["source_body_sha256"]]
        r["candidate_body_shas"] = sorted(bodies)
        r["addresses_checked"] = sorted(set(targets + [r["source_url"]]))
        r["delivered_target_pdf_shas"] = [
            s
            for s in sorted(bodies)
            if live[s]["export"]
            and any(d["format"] == "pdf" and not d["hidden"] for d in live[s]["documents"])
        ]
        require(r["delivered_target_pdf_shas"], f"missing landing target {r['case_id']}")
    selected = query(
        db, "SELECT count(*) n FROM (SELECT body_sha,parser FROM selected GROUP BY ALL HAVING count(*)>1)"
    )
    require(selected[0]["n"] == 0, "multiple selected reading versions")
    for body_sha, r in live.items():
        r["source_exclusion"] = excluded.get(body_sha)
        if r["export"]:
            r["export"].pop("page_offsets")  # source-role evidence only needs export membership/digest
    qualification = serializable(
        query(
            db,
            "SELECT requested_url,capture_reason,capture_disposition,last_status FROM url_state WHERE capture_reason='body_not_qualified' ORDER BY requested_url",
        )
    )
    unopened = [
        r["body_sha256"]
        for r in lines(root / ASSESSMENT / "response-examples-20261114/examples.jsonl")
        if r["expected_error_response"] is None
    ]
    require(len(unopened) == 14 and not set(unopened) & keys_in_inventory, "unassessed template siblings")
    db.close()
    summary = dict(
        inventory=len(rows),
        inventory_buckets=counts,
        historical_provenance=Counter(r["kind"] for r in provenance.values()),
        zero_page_buckets=Counter(r["bucket"] for r in zeros),
        overlap=len(keys_in_inventory & zero_by_sha.keys()),
        public_saved_hashes=sum(bool(r["live"]["documents"]) for r in rows),
        public_saved_rows=sum(len(r["live"]["documents"]) for r in rows),
        unhidden_saved_rows=sum(not d["hidden"] for r in rows for d in r["live"]["documents"]),
        inventory_exported=sum(r["live"]["export"] is not None for r in rows),
        pdf_errors=len(pdf_errors),
        inventory_pdf_errors=sum(r["in_inventory"] for r in pdf_errors),
        inventory_recovery_open=sum(r["operational"]["recovery_open"] for r in rows),
    )
    copy_check = public_copy_control(rows)
    write(
        out / "ct-en4n-reconciliation.json",
        dict(
            release=RELEASE,
            export=EXPORT,
            selection=SELECTION,
            summary=summary,
            inputs={
                str(p): fingerprint(root / p)
                for p in (
                    INVENTORY,
                    OLD,
                    OUT / "receipt-provenance.json",
                    OUT / "capture-history.parquet",
                    OUT / "selected-readings.parquet",
                    OUT / "zero-page-structure.json",
                )
            },
            public_copy_control=copy_check,
            inventory=rows,
            zero_page=zeros,
            pdf_errors=pdf_errors,
            addresses=addresses,
            source_controls=positive,
            archive_error_wrappers=wrappers,
            reviewed_landings=landings,
            release_body_not_qualified=qualification,
            unassessed_template_siblings=unopened,
            associated_body_state=live,
        ),
    )
    report(root, summary, rows, positive)

    print(summary)
    return copy_check


def report(root, summary, rows, positive):
    damaged = [r for r in rows if r["live"]["documents"] and r["failure_category"] != "error_response"]
    bad_downloads = [d for r in rows for d in r["live"]["documents"] if not d["hidden"]]
    content = f"""# Source-role reconciliation for November 20

All 455 source records have a role. The live v13 export contains zero of their original body hashes. Explorer still exposes {len(bad_downloads)} unhidden saved copies from this inventory. The public-copy exclusion check therefore fails.

Release `{RELEASE}` and v13 export `{EXPORT}` use selection `{SELECTION}`. Each ledger row retains its evidence, exact capture coordinates, source eligibility, URL-state lookup, public link keys, recovery associations and selection outcome.

| Inventory role | Bodies |
| --- | ---: |
""" + "".join(f"| {role} | {n} |\n" for role, n in sorted(summary["inventory_buckets"].items()))
    content += """
The original receipt line and capture index resolve all 188 historical provenance gaps. Each of the 187 embedded House HTML responses has a meeting ID that matches its form action. One Senate security response is a verified retained listing file. The reconstructed source addresses are identified separately from the HTTP request field, which was absent on the original observations. None establishes a missing PDF target. The 197 NoSuchKey playlist responses belong to recording history. All have HTTP error captures and zero public saved-body associations.

| Earlier zero-page diagnostic | Bodies |
| --- | ---: |
""" + "".join(f"| {role} | {n} |\n" for role, n in sorted(summary["zero_page_buckets"].items()))
    content += f"""
Fifty of these 345 SHA values also occur in the 455-record inventory. Each of the 345 has a PDF source header and a documented defect or incomplete transfer. None has delivered v13 text. The transfer buckets report the observed failure or limit. They do not assign the origin of the missing bytes to the publisher.

**Live exposure.** {summary['public_saved_hashes']} distinct inventory hashes are saved on {summary['public_saved_rows']} Explorer rows. The {len(damaged)} damaged PDFs with saved-body associations still have an unhidden saved-copy link. Two State Department HTML errors also have unhidden links. Four Natural Resources HTML errors occupy five hidden recovery rows, including the separate Bakst and Mitchell targets. All 398 inventory error responses carry explicit v13 error exclusions. Both State archive wrappers share the payload receipt and have their own exclusions. The public URL-state table has one `body_not_qualified` entry, outside the 455. It does not retrospectively label every damaged source.

Exactly {summary['inventory_pdf_errors']} of the 27 selected public PDF error readings belong to the inventory. Twenty-one have the historical zero-page diagnostic, and one is the Walling source. The other five failures are named separately in the ledger. These are reading statuses. The export itself contains only saved body, text, offsets and digest.

**Controls and recovery.** The ledger names {len(positive)} positive controls, including legitimate XML, a meeting landing page, the full Atom feed, a CRC-checked ZIP, statute viewers, reviewed empty results and documents mentioning error phrases. Fourteen example siblings remain unassessed. All eight reviewed landing targets have a current public PDF and v13 text. The three earlier scoped alternatives retain their revision limits. The November 20 recovery inventory reports 26 closed and {summary['inventory_recovery_open']} open exact-original obligations. Per-target acquisition decisions remain with ct-z4w5.

The HTTP control compares actual failed receipts and served body hashes with the public release. The good-fetch rule in `model/sql/good-fetches.sql` requires HTTP 200–299. Ticket ct-fb29 documents release-schema descriptions. The historical wrappers, raw receipts and completed reading history remain available through the evidence files.

**Reproduce** from the isolated checkout with its frozen Python environment. Run each of `scripts/measure/pdf_source_evidence.py`, `pdf_source_structure.py`, `pdf_source_history.py`, `reconcile_ct_en4n_source_roles.py` and `reconcile_ct_kfsd_cleanup.py` with the archive-release directory as its only argument and the requested archive watchdog. The first three produce the read-only evidence inputs. The latter two produce the ledgers. The full text column is only opened in row groups containing one of the 56 named readbacks.

The source-role command writes the complete ledger and returns exit 1 when the public-copy check finds an unhidden invalid download.
"""
    (root / OUT / "ct-en4n-summary.md").write_text(content)


if __name__ == "__main__":
    result = reconcile(archive_arg())
    if not result["passed"]:
        raise SystemExit(
            f"Public-copy exclusion failed for {len(result['unhidden_saved_copies'])} unhidden saved copies."
        )

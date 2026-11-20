"""Verify source roles, capture history, recovery and public exposure on the November 20 release."""

from collections import Counter, defaultdict
import csv
from hashlib import sha256
import gzip
import json
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
from pdf_source_structure import zero_page_addresses, zero_page_rows
from pdf_source_release import exposure, query, release_db, serializable

ASSESSMENT = OCR / "repairs/corpus-assessment-20261113"
OLD = Path("ticket-fixes-20261117/inventory/post-capture-append/invalid-sources.jsonl")
PROPOSAL = OCR / "repairs/response-roles-offline-20261113/deferred-source-proposal.json"
VIEWERS = ASSESSMENT / "triage-current-20261114/ct-g4yz-fallback-release-binding-20261115/binding.json"
EMPTY_CONTROLS = (
    OCR / "repairs/accepted-text-adoption-20261114/accepted-set-v11/known-valid-empty-bodies.json"
)
PHRASES = Path("investigations/text-quantity-review-20261113/error-review-notes.jsonl")
PHRASE_SAMPLES = PHRASES.with_name("error-review-samples.json")
CONTROL_INPUTS = {
    EMPTY_CONTROLS: "fa337f5e82b1797e2f131a87c6e84924b2ce0601c94fa828403bea8739b3dfc4",
    PHRASES: "987c1d761522ad865c66e49fc797f17cc5981de898328d37339706253c86a26c",
    PHRASE_SAMPLES: "57a59462bb68cf6ddcededd9e506a0c2f9650dcd20059f0a0538a10f50dd45a0",
}
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
    for path, digest in CONTROL_INPUTS.items():
        require(fingerprint(root / path) == digest, f"changed reviewed control input {path}")
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
    empty_controls = load(root / EMPTY_CONTROLS)
    require(len(set(empty_controls)) == 57, "public valid-empty control set")
    for sha in empty_controls:
        positive[sha] = dict(
            role="reviewed_valid_empty_reading",
            evidence=str(EMPTY_CONTROLS),
            expected_visible_documents=1,
            expected_text_sha256=EMPTY,
        )
    samples = {s["body_sha256"]: s for s in load(root / PHRASE_SAMPLES)}
    for r in lines(root / PHRASES):
        if r["classification"] == "ordinary-document-mentions-error-related-words":
            sample = samples[r["body_sha256"]]
            require(
                sample["review_id"] == r["review_id"] and sample["text_sha256"] != EMPTY,
                "quotation control review identity",
            )
            positive[r["body_sha256"]] = dict(
                role="ordinary_document_quoting_error_language",
                evidence=str(PHRASES),
                text_evidence=str(PHRASE_SAMPLES),
                review_id=r["review_id"],
                expected_visible_documents=r["unhidden_selected_documents"],
                expected_text_sha256=sample["text_sha256"],
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
    if role in ("reviewed_valid_empty_reading", "ordinary_document_quoting_error_language"):
        visible = sum(not d["hidden"] for d in state["documents"])
        require(visible == info["expected_visible_documents"], f"{sha} reviewed control exposure")
        if state["documents"] or state["export"] is not None:
            require(
                state["export"] and state["export"]["text_sha256"] == info["expected_text_sha256"],
                f"{sha} reviewed text digest changed",
            )
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


def public_copy_control(rows, wrappers):
    """Check Explorer's list filter and its detail download link for each saved-body association."""
    records = []
    for row in [*rows, *wrappers.values()]:
        for doc in row["live"]["documents"]:
            records.append(
                dict(
                    body_sha256=row["body_sha256"],
                    recovery_payload_sha256=row.get("payload_sha256", row["body_sha256"]),
                    bucket=row["bucket"],
                    **doc,
                    default_list_visible=not doc["hidden"],
                    detail_download_available=doc["saved_body"] is not None,
                )
            )
    visible = sum(d["default_list_visible"] for d in records)
    downloads = sum(d["detail_download_available"] for d in records)
    return dict(
        passed=not (visible or downloads),
        default_list_passed=visible == 0,
        detail_downloads_passed=downloads == 0,
        default_list_visible=visible,
        detail_downloads=downloads,
        records=records,
    )


def recovery_record(item, fact, bucket, addresses):
    """Preserve exact-original recovery decisions and qualify document acquisition separately."""
    row = dict(item, source_role=bucket)
    if fact:
        eligibility = "no_document_target"
        url = fact["source_url"]
        captures = addresses[url]["captures"]
        role = {
            "embedded_house_meeting_fallback": "house_meeting_listing_member",
            "retained_senate_listing_security_response": "senate_hearings_listing",
        }[fact["kind"]]
        row.update(
            source_role=role,
            source_urls=[url],
            receipt_provenance=fact,
            source_validity="error_response_at_listing",
            needs_refetch=False,
            capture_history=dict(
                item["capture_history"],
                status="listing_address_reconstructed_from_receipt",
                predecessor_status=item["capture_history"]["status"],
            ),
            recovery_state="listing_identified_no_document_target",
            next_action="retain_listing_evidence",
            targets=[
                dict(
                    requested_target=url,
                    source_role=role,
                    url_basis=fact["url_basis"],
                    http_requested_url=fact["http_requested_url"],
                    observed_aliases=sorted(
                        {u for c in captures for u in (c["requested_url"], c["url"]) if u}
                    ),
                    other_body_candidates=sorted(
                        {
                            c["body_sha256"]
                            for c in captures
                            if c["body_sha256"] and c["body_sha256"] != item["body_sha256"]
                        }
                    ),
                    capture_observations=len(captures),
                    recovery_open=row["recovery_open"],
                    qualification=eligibility,
                    dispatch_enabled=False,
                    dispatch_reason="Receipt identifies a listing and supplies no document target.",
                )
            ],
        )
    elif bucket == "missing_recording_playlist":
        eligibility = "recording_only"
        row.update(next_action="retain_for_recording_recovery")
    elif row["needs_refetch"] is True:
        eligibility = "review_target_before_fetch"
        if row["next_action"] == "resolve_source_url_and_capture_history":
            row.update(recovery_state="needs_source_recovery", next_action="review_alternatives_or_refetch")
    elif row["needs_refetch"] is None:
        eligibility = "pending_target_qualification"
    else:
        eligibility = "no_publisher_refetch"
    row["document_fetch_eligibility"] = eligibility
    row["targets"] = [dict(t, document_fetch_eligibility=eligibility) for t in row["targets"]]
    return row


def write_handoff(out, handoff):
    """Keep the existing JSONL and CSV entry points for recovery and text-quality consumers."""
    path = out / "invalid-sources.jsonl"
    fields = (
        "record_id",
        "body_sha256",
        "failure_category",
        "recovery_open",
        "needs_refetch",
        "recovery_state",
        "next_action",
        "resolution",
        "source_role",
        "document_fetch_eligibility",
    )
    with path.open("w") as stream, (out / "invalid-sources.csv").open("w", newline="") as view:
        writer = csv.DictWriter(view, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in handoff:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            writer.writerow(record)
    open_count = sum(r["recovery_open"] for r in handoff)
    summary = dict(
        total_rows=len(handoff),
        recovery_open=open_count,
        already_covered=len(handoff) - open_count,
        needs_refetch=sum(r["needs_refetch"] is True for r in handoff),
        refetch_requires_history_review=sum(
            r["recovery_state"] == "needs_capture_history_review" for r in handoff
        ),
        document_fetch_eligibility=Counter(r["document_fetch_eligibility"] for r in handoff),
    )
    write(out / "inventory-summary.json", summary)
    return dict(path=str(OUT / path.name), sha256=fingerprint(path))


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
    zero_urls = {url for row in zeros for url in zero_page_addresses(row)}
    require(len(zero_urls) == 382, "zero-page address coverage")
    urls.update(zero_urls)
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
    # This hearing had a capped transfer and a later successful capture with different bytes.
    hearing_url = "https://www.govinfo.gov/content/pkg/CHRG-118shrg53785/pdf/CHRG-118shrg53785.pdf"
    hearing_sha = "1e68f460bf1cd70f81721d5aa0d533ab016016142d1224c18b83ba4945f237f4"
    require(
        any(
            c["body_sha256"] == hearing_sha
            and c["outcome"] == "stored"
            and c["complete"]
            and c["retrieved_at"].startswith("2026-10-06")
            for c in addresses[hearing_url]["captures"]
        )
        and any(
            d["doc_id"] == "1e68f460bf1cd70f" and d["format"] == "pdf" and not d["hidden"]
            for d in live[hearing_sha]["documents"]
        ),
        "missing October 6 GovInfo capture or public PDF",
    )
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
    handoff = []
    for r in inventory:
        sha = r["body_sha256"]
        fact = provenance.get(sha)
        bucket = source_bucket(r, fact)
        r = recovery_record(r, fact, bucket, addresses)
        targets = r["source_urls"]
        # The same empty body occurs at unrelated URLs. Keep this obligation scoped to Cornwell.
        captures = (
            history[sha]
            if sha != EMPTY
            else [c for c in addresses[targets[0]]["captures"] if c["body_sha256"] == sha]
        )
        row = dict(
            record_id=r["record_id"],
            body_sha256=sha,
            bucket=bucket,
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
                    "source_role",
                    "document_fetch_eligibility",
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
        handoff.append(
            dict(
                r,
                exclusion=excluded.get(sha),
                selected_readings=live[sha]["readings"],
                v13_exported=live[sha]["export"] is not None,
            )
        )
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
        source_urls = sorted(zero_page_addresses(r))
        r.update(
            in_inventory=sha in keys_in_inventory,
            live=live[sha],
            addresses=source_urls,
            captured_body_shas=sorted(
                {c["body_sha256"] for u in source_urls for c in addresses[u]["captures"] if c["body_sha256"]}
            ),
        )
    require(
        {s for r in rows if r["failure_category"] == "error_response" for s in r["archive_wrapper_shas"]}
        == wrappers.keys(),
        "linked error wrappers missing from release check",
    )
    for sha, r in wrappers.items():
        payload = r["payload_sha256"]
        require(
            (excluded.get(sha) or {}).get("source_role") == "error_response" and live[sha]["export"] is None,
            "archive wrapper error exclusion",
        )
        r.update(bucket="archive_wrapper_of_error_response", live=live[sha])
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
    copy_check = public_copy_control(rows, wrappers)
    summary = dict(
        inventory=len(rows),
        inventory_buckets=counts,
        historical_provenance=Counter(r["kind"] for r in provenance.values()),
        zero_page_buckets=Counter(r["bucket"] for r in zeros),
        overlap=len(keys_in_inventory & zero_by_sha.keys()),
        public_saved_hashes=sum(bool(r["live"]["documents"]) for r in rows),
        public_saved_rows=sum(len(r["live"]["documents"]) for r in rows),
        zero_page_addresses=len(zero_urls),
        default_list_visible_including_wrappers=copy_check["default_list_visible"],
        detail_downloads_including_wrappers=copy_check["detail_downloads"],
        inventory_exported=sum(r["live"]["export"] is not None for r in rows),
        pdf_errors=len(pdf_errors),
        inventory_pdf_errors=sum(r["in_inventory"] for r in pdf_errors),
        inventory_recovery_open=sum(r["operational"]["recovery_open"] for r in rows),
    )
    inventory_pin = write_handoff(out, handoff)
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
                    *CONTROL_INPUTS,
                    OUT / "receipt-provenance.json",
                    OUT / "capture-history.parquet",
                    OUT / "selected-readings.parquet",
                    OUT / "zero-page-structure.json",
                )
            },
            recovery_inventory=inventory_pin,
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
    report(root, summary, positive)

    print(summary)
    return copy_check


def report(root, summary, positive):
    content = f"""# Source-role reconciliation for November 20

All 455 source records have a role. The v13 export contains zero original inventory hashes. Across the inventory and its two linked State Department archive wrappers, {summary['default_list_visible_including_wrappers']} records appear in Explorer's default list and {summary['detail_downloads_including_wrappers']} detail pages offer unqualified saved copies. Ticket ct-qmh5 tracks their release suppression.

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
Fifty of these 345 SHA values also occur in the 455-record inventory. Each of the 345 has a PDF source header and a documented defect or incomplete transfer. None has delivered v13 text. The capture query covers all {summary['zero_page_addresses']} zero-page addresses. For CHRG-118shrg53785 the October 5 batch reached its size limit. The October 6 capture stored the complete PDF offered at Explorer link `1e68f460bf1cd70f`. Each zero-page record names the body hashes captured at its addresses and the ledger gives their release associations.

**Live exposure.** {summary['public_saved_hashes']} distinct inventory hashes are saved on {summary['public_saved_rows']} Explorer rows. The default list includes 22 damaged PDFs, two State Department HTML errors and both archive wrappers. The wrapper link keys are `6eea94ddc3e78724` and `b6aaf0d8fdba71e2`. Each wrapper shares its payload's recovery record. Four Natural Resources HTML errors occupy five hidden rows, including the separate Bakst and Mitchell targets. All five detail pages still offer the saved body. All 398 inventory error responses and both wrappers carry explicit v13 error exclusions. The public URL-state table has one `body_not_qualified` entry, outside the 455.

Exactly {summary['inventory_pdf_errors']} of the 27 selected public PDF error readings belong to the inventory. Twenty-one have the historical zero-page diagnostic, and one is the Walling source. The other five failures are named separately in the ledger. These are reading statuses. The export itself contains only saved body, text, offsets and digest.

**Controls and recovery.** The ledger names {len(positive)} positive controls, including legitimate XML, a meeting landing page, the full Atom feed, a CRC-checked ZIP and statute viewers. All 57 reviewed valid-empty readings retain public documents and the empty-text digest. Public documents quoting error language retain the text digest from their source review. Fourteen example siblings remain unassessed. All eight reviewed landing targets have a current public PDF and v13 text. The three earlier scoped alternatives retain their revision limits. The successor `invalid-sources.jsonl` preserves the 26 closed and {summary['inventory_recovery_open']} open exact-original decisions from ct-z4w5 and gives document-fetch eligibility for each source and target. No document fetch is eligible for the 188 reconstructed listings or the 197 recording playlists.

The HTTP control compares actual failed receipts and served body hashes with the public release. The good-fetch rule in `model/sql/good-fetches.sql` requires HTTP 200–299. Ticket ct-fb29 documents release-schema descriptions. The historical wrappers, raw receipts and completed reading history remain available through the evidence files.

**Reproduce** from the isolated checkout with its frozen Python environment. Run each of `scripts/measure/pdf_source_evidence.py`, `pdf_source_structure.py`, `pdf_source_history.py`, `reconcile_ct_en4n_source_roles.py` and `reconcile_ct_kfsd_cleanup.py` with the archive-release directory as its only argument and the requested archive watchdog. The first three produce the read-only evidence inputs. The latter two produce the ledgers. The full text column is only opened in row groups containing one of the 56 named readbacks.

The source-role command writes the inventory and ledger before returning exit 1 if an invalid saved body appears in the default list or a detail page offers it for download.
"""
    (root / OUT / "ct-en4n-summary.md").write_text(content)


if __name__ == "__main__":
    result = reconcile(archive_arg())
    if not result["passed"]:
        raise SystemExit(
            f"Public-copy exclusion failed. {result['default_list_visible']} records in the default list, "
            f"{result['detail_downloads']} detail pages offering unqualified downloads."
        )

"""House retained source groups, with explicit limits for legacy flattened state."""

import re

from committee_meeting.assessments import Assessment
from committee_meeting.common import Identifier
from committee_meeting.issues import DataIssue
from committee_meeting.legislation import Amendment, AmendmentGroup, AmendmentSponsor, LegislativeItem, Vote
from committee_meeting.materials import DocumentDetails, MaterialLink
from committee_meeting.meetings import Affiliation, Appearance, Panel, Person, RecordedName

from congress_api.adapters.common import digest, material_records, observed_time, ref, web_url, witness_roles
from congress_api.adapters.meetings import category, DOCUMENT_CATEGORIES as MEETING_DOCUMENT_CATEGORIES
from congress_api.parsers.document_types import DOCUMENT_TYPE_MEANINGS
from congress_api.models.house import HouseParsedRecord

DOCUMENT_CATEGORIES = {alias.upper(): MEETING_DOCUMENT_CATEGORIES[meaning]
                       for alias, meaning in DOCUMENT_TYPE_MEANINGS.items()
                       if len(alias) == 2 and alias != 'sd' and meaning in MEETING_DOCUMENT_CATEGORIES}


def value(meta, path):
    for part in path.split("/"):
        meta = next((c for c in meta.get("children", []) if c["tag"] == part), {})
    return (meta.get("text") or "").strip()


def number(raw):
    return int(raw) if str(raw).isdigit() else None


def document_key(key, group, owners):
    urls = sorted({f["url"] for f in group.get("files", []) if f.get("active", True) and web_url(f.get("url"))})
    stable = group.get("metadata", {}).get("attributes", {}).get("add-date")
    owner = owners.get(group.get("owning_witness_selector"))
    return key + "|document|" + (stable + "|" + group.get("source", "") + "|" + (owner.id if owner else "") + "|" + ("|".join(urls) or digest(group))
                                if stable else "|".join(urls) or digest(group))


def alias_legacy_documents(context, key, saved, groups, owners):
    """Preserve published IDs only for unambiguous old→rich file correspondence."""
    alias = getattr(context.ids, "alias", None)
    existing = getattr(context.ids, "existing", None)
    if alias is None or existing is None:
        return
    by_url = {}
    for group in groups:
        if not group.get("active", True):
            continue
        rich_key = document_key(key, group, owners)
        for file in group.get("files", []):
            if file.get("active", True) and web_url(file.get("url")):
                by_url.setdefault(file["url"].replace("http://", "https://"), set()).add(rich_key)
    pairs, old_by_rich = {}, {}
    for document in saved.get("documents", []):
        old_key = key + "|document|" + document[2]
        candidates = by_url.get(document[2].replace("http://", "https://"), set())
        if len(candidates) != 1:
            continue
        rich_key = next(iter(candidates))
        pairs[old_key] = rich_key
        old_by_rich.setdefault(rich_key, set()).add(old_key)
    for old_key, rich_key in pairs.items():
        if len(old_by_rich[rich_key]) != 1:
            continue
        if alias("material", rich_key, old_key):
            alias("material_version", rich_key + "|reported-edition", old_key + "|reported-edition")


def records(state, context, *, meetings):
    for event, saved in sorted(state.items()):
        # Typed parser output and historical dictionary imports share the same
        # source fields; neither normalization path depends on a storage format.
        if isinstance(saved, HouseParsedRecord):
            saved = saved.source_dict()
        matches = [(k, v) for k, v in meetings.items() if k[2] == str(event) and k[1] in ("house", "joint")]
        meeting = matches[0][1] if len(matches) == 1 else None
        congress = matches[0][0][0] if len(matches) == 1 else None
        key = f"docs.house.gov|{congress}|{event}"
        source = context.source(key, saved, (saved.get("urls") or [None])[0])
        check = saved.get("last_check") or {}
        check = check if isinstance(check, dict) else {}
        observed = observed_time(saved.get("retrieved_at"), context.now) if check.get("mode") == "live" and not saved.get("replay") else None
        if observed is not None:
            source = source.model_copy(update={"retrieved_at": observed})
        yield source
        evidence = context.evidence(source, basis="derived", method="congress_api.house.retained-output")
        if check.get("mode") == "live" and not saved.get("replay") and saved.get("retrieved_at") is not None and observed is None:
            yield DataIssue(id=context.ids("data_issue", key + "|invalid-retrieval-time"), subject=ref(source), category="unverified",
                            summary="The retained House retrieval time could not be used", field_path="/retrieved_at",
                            explanation="Retrieval times must include a timezone and cannot be later than this export. The original value remains in the source payload.",
                            detected_at=context.now, provenance=context.evidence(source, selector="/retrieved_at"))
        if check.get("mode") == "live" and check.get("outcome") == "error":
            completed = observed_time(check.get("completed_at"), context.now)
            check_evidence = context.evidence(source, selector="/last_check")
            yield DataIssue(id=context.ids("data_issue", key + "|failed-refresh"), subject=ref(source), category="unverified",
                            summary="The latest House source refresh failed", detected_at=context.now, last_checked_at=completed,
                            explanation="Previously retained documents and witnesses remain available. This failed check does not establish absence.", provenance=check_evidence)
            if meeting:
                receipts = check.get("receipts") or []
                urls = [row["url"] for row in receipts if isinstance(row, dict) and web_url(row.get("url"))] if isinstance(receipts, list) else []
                scope = "; ".join(dict.fromkeys(urls)) or f"docs.house.gov meeting source check for event {event}"
                yield Assessment(id=context.ids("assessment", key + "|reachability"), subject=meeting,
                                 aspect="reachability", status="error", evaluated_at=context.now, observed_at=completed,
                                 provider=context.provider, scope=scope,
                                 explanation="The latest refresh failed. Retained results remain historical source observations.", provenance=check_evidence)
        rich = saved.get("evidence") or {}
        if not rich:
            yield DataIssue(id=context.ids("data_issue", key + "|legacy-state"), subject=ref(source), category="unverified",
                            summary="Legacy House state omits alternate file URLs and source ownership", detected_at=context.now, provenance=evidence)
        if meeting is None:
            yield DataIssue(id=context.ids("data_issue", key + "|unlinked"), subject=ref(source), category="unlinked",
                            summary="House source has no unambiguous meeting in this export", detected_at=context.now, provenance=evidence)
        owners = {}
        panels = {}
        if meeting:
            for i, panel in enumerate(rich.get("panels", [])):
                if panel.get("active", True) is False:
                    continue
                p = Panel(id=context.ids("panel", key + "|panel|" + panel.get("sort_order", panel["selector"])), meeting=meeting,
                          order=number(panel.get("sort_order")), provenance=context.evidence(source, selector=f"/evidence/panels/{i}"))
                panels[panel["selector"]] = ref(p)
                yield p
            observations = rich.get("witness_observations")
            witnesses = observations if observations is not None else saved.get("witnesses", [])
            for i, w in enumerate(witnesses):
                if w.get("active", True) is False or not w.get("name", "").strip():
                    continue
                meta = w.get("metadata", {})
                get = lambda tag, legacy=None: value(meta, tag) or w.get(legacy or tag) or None
                name = w["name"]
                witness_key = key + "|witness|" + name
                # Same-name observations remain separate, with explicit uncertainty.
                if sum(o.get("name") == name and o.get("active", True) for o in witnesses) > 1:
                    witness_key += "|" + digest({"metadata": meta, "selector": w["selector"]} if w.get("selector") else w)
                    yield DataIssue(id=context.ids("data_issue", key + "|ambiguous-witness|" + name), subject=meeting,
                                    category="duplicate", summary="Same-name House witnesses need correspondence review", detected_at=context.now, provenance=evidence)
                bio = get("bioguideID", "bioguide_id")
                person = None
                if bio:
                    person = Person(id=context.ids("person", "bioguide|" + bio), name=name,
                                    identifiers=(Identifier(scheme="bioguide", value=bio),), provenance=evidence)
                    yield person
                testified = get("testified") or meta.get("attributes", {}).get("testified")
                position = get("position")
                a = Appearance(id=context.ids("appearance", witness_key), meeting=meeting, person=ref(person) if person else None,
                               panel=panels.get(w.get("panel_selector")), name=RecordedName(display=name, given=get("firstname", "first"), family=get("lastname", "last"),
                               honorific=get("honorific"), middle=get("middlename", "middle"), suffix=get("suffix"), retired=get("retired")), roles=witness_roles(position),
                               participation="testified" if str(testified).lower() in ("true", "yes", "1") else "listed",
                               affiliation=Affiliation(position=position, organization_name=get("organization"), on_behalf_of=get("behalf-of", "behalf_of"), location=get("location")),
                               order=number(w.get("display_order")), provenance=context.evidence(source, selector=f"/evidence/witness_observations/{i}" if observations is not None else f"/witnesses/{i}"))
                owners[w.get("selector", "")] = ref(a)
                yield a
        groups = rich.get("document_groups")
        if groups is None:
            groups = [{"type": "", "description": d[1], "files": [{"url": d[2]}], "legacy_kind": d[0]} for d in saved.get("documents", [])]
        elif saved.get("documents"):
            alias_legacy_documents(context, key, saved, groups, owners)
        enbloc, enbloc_evidence, document_materials = {}, {}, {}
        for i, group in enumerate(groups):
            if group.get("active", True) is False:
                continue
            for file_index, file in enumerate(group.get("files", [])):
                if file.get("active", True) and file.get("url") and not web_url(file["url"]):
                    selector = f"/evidence/document_groups/{i}/files/{file_index}/url" if rich.get("document_groups") is not None else f"/documents/{i}/2"
                    yield DataIssue(id=context.ids("data_issue", key + "|invalid-file-url|" + digest(file["url"])), subject=ref(source), category="incorrect",
                                    summary="A House source file URL is malformed", detected_at=context.now,
                                    explanation="The original value remains in source evidence. It cannot be offered as an absolute HTTP(S) download URL without a verified correction.",
                                    provenance=context.evidence(source, selector=selector))
            urls = sorted({f["url"] for f in group.get("files", []) if f.get("active", True) and web_url(f.get("url"))})
            meta = group.get("metadata", {})
            dkey = document_key(key, group, owners)
            ev = context.evidence(source, basis="derived", method="congress_api.house.retained-output", selector=f"/evidence/document_groups/{i}" if rich.get("document_groups") is not None else f"/documents/{i}")
            code = group.get("type")
            cat = DOCUMENT_CATEGORIES.get(code) or category({"kind": group.get("legacy_kind"), "name": group.get("description")})
            if cat == "unknown":
                cat = next((kind for word, kind in (("notice", "notice"), ("agenda", "agenda")) if re.search(r"\b" + word + r"\b", group.get("description", ""), re.I)), cat)
            if cat == "unknown" and code == "SD":
                cat = "supporting"
            subject = owners.get(group.get("owning_witness_selector")) or meeting
            role = "vote_record" if cat == "vote" else cat if cat in ("amendment", "transcript", "statement", "biography", "disclosure", "questions_for_record", "notice", "agenda") else "supporting"
            mapped = material_records(context, ev, dkey, title=group.get("description"), urls=urls, details=DocumentDetails(category=cat), subject=subject, role=role)
            yield from mapped
            for url in urls:
                document_materials[url] = mapped[:2]
            if not meeting or code not in ("CA", "HA", "FA", "CV"):
                continue
            target = None
            bill = value(meta, "legis-num") or value(meta, "filename-metadata/legis-num")
            if re.fullmatch(r"(?:H\.?\s*R\.?|H\.?\s*(?:J\.?|Con\.?)?\s*Res\.?|S\.?\s*(?:(?:J\.?|Con\.?)?\s*Res\.?)?)\s*\d+", bill, re.I):
                item = LegislativeItem(id=context.ids("legislative_item", f"house|{congress}|{bill}"), congress=congress, designation=bill,
                                       item_type="resolution" if re.search("res", bill, re.I) else "bill", provenance=ev)
                yield item
                target = ref(item)
            action_key = dkey + "|action"
            if code == "CV":
                action = Vote(id=context.ids("vote", action_key), meeting=meeting, subject=target, number=value(meta, "filename-metadata/vote-num") or None, question=group.get("description") or None, provenance=ev)
            else:
                sponsors = []
                bio = value(meta, "filename-metadata/bioguideID")
                if bio:
                    p = Person(id=context.ids("person", "bioguide|" + bio), identifiers=(Identifier(scheme="bioguide", value=bio),), provenance=ev)
                    yield p
                    sponsors.append(AmendmentSponsor(person=ref(p), role="sponsor", provenance=ev))
                action = Amendment(id=context.ids("amendment", action_key), meeting=meeting, target=target, number=value(meta, "filename-metadata/amdt-num") or None,
                                   amendment_type=value(meta, "filename-metadata/amdt-type") or None, description=group.get("description") or None, sponsors=tuple(sponsors), provenance=ev)
                label = value(meta, "filename-metadata/enbloc-num")
                if label:
                    enbloc.setdefault(label, []).append(ref(action))
            yield action
            yield MaterialLink(id=context.ids("material_link", dkey + "|action"), material=ref(mapped[0]), version=ref(mapped[1]), subject=ref(action), role=role, provenance=ev)
        if meeting and rich.get("document_groups") is None:
            # Legacy read_xml emitted one row per file format. Retain every row
            # as evidence, but identical action metadata describes one action.
            actions = {}
            for i, row in enumerate(saved.get("amendments", [])):
                ev = context.evidence(source, basis="derived", method="congress_api.house.read_xml", selector=f"/amendments/{i}")
                if not isinstance(row, dict) or row.get("kind") not in ("amendment", "vote") or any(
                    row.get(field) is not None and not isinstance(row[field], str)
                    for field in ("bill", "number", "sponsor_bioguide", "amendment_type", "enbloc", "description", "url")
                ):
                    yield DataIssue(id=context.ids("data_issue", key + f"|invalid-action|{i}"), subject=ref(source), category="unverified",
                                    summary="A retained House action row could not be interpreted", detected_at=context.now, provenance=ev)
                    continue
                metadata = {field: row.get(field) or "" for field in ("kind", "bill", "number", "sponsor_bioguide", "amendment_type", "enbloc", "description")}
                action_key = key + "|legacy-action|" + digest(metadata)
                retained = actions.setdefault(action_key, {"metadata": metadata, "evidence": [], "urls": {}})
                retained["evidence"].append(ev)
                if row.get("url"):
                    retained["urls"].setdefault(row["url"], ev)
            for action_key, retained in actions.items():
                row = retained["metadata"]
                ev = retained["evidence"][0].model_copy(update={"citations": tuple(c for p in retained["evidence"] for c in p.citations)})
                target = None
                bill = row["bill"]
                if re.fullmatch(r"(?:H\.?\s*R\.?|H\.?\s*(?:J\.?|Con\.?)?\s*Res\.?|S\.?\s*(?:(?:J\.?|Con\.?)?\s*Res\.?)?)\s*\d+", bill, re.I):
                    item = LegislativeItem(id=context.ids("legislative_item", f"house|{congress}|{bill}"), congress=congress,
                                           designation=bill, item_type="resolution" if re.search("res", bill, re.I) else "bill", provenance=ev)
                    yield item
                    target = ref(item)
                role = "vote_record" if row["kind"] == "vote" else "amendment"
                if row["kind"] == "vote":
                    action = Vote(id=context.ids("vote", action_key), meeting=meeting, subject=target,
                                  number=row["number"] or None, question=row["description"] or None, provenance=ev)
                else:
                    sponsors = []
                    bio = row["sponsor_bioguide"]
                    if bio:
                        person = Person(id=context.ids("person", "bioguide|" + bio), identifiers=(Identifier(scheme="bioguide", value=bio),), provenance=ev)
                        yield person
                        sponsors.append(AmendmentSponsor(person=ref(person), role="sponsor", provenance=ev))
                    action = Amendment(id=context.ids("amendment", action_key), meeting=meeting, target=target,
                                       number=row["number"] or None, description=row["description"] or None,
                                       amendment_type=row["amendment_type"] or None, sponsors=tuple(sponsors), provenance=ev)
                    if row["enbloc"]:
                        enbloc.setdefault(row["enbloc"], []).append(ref(action))
                        enbloc_evidence.setdefault(row["enbloc"], []).append(ev)
                yield action
                for url, file_evidence in retained["urls"].items():
                    if not web_url(url):
                        yield DataIssue(id=context.ids("data_issue", action_key + "|invalid-url|" + digest(url)), subject=ref(action), category="unverified",
                                        summary="A House action's attachment URL is not an absolute HTTP(S) URL", detected_at=context.now, provenance=file_evidence)
                        continue
                    mapped = document_materials.get(url)
                    if mapped is None:
                        # This URL is explicitly retained in the action row;
                        # basename similarity never establishes file ownership.
                        mapped = material_records(context, file_evidence, key + "|document|" + url, title=row["description"], urls=[url],
                                                  details=DocumentDetails(category="vote" if row["kind"] == "vote" else "amendment"), subject=meeting, role=role)
                        yield from mapped
                        document_materials[url] = mapped[:2]
                    yield MaterialLink(id=context.ids("material_link", action_key + "|attachment|" + url), material=ref(mapped[0]), version=ref(mapped[1]),
                                       subject=ref(action), role=role, provenance=file_evidence)
        for label, members in enbloc.items():
            group_evidence = evidence
            if label in enbloc_evidence:
                group_evidence = enbloc_evidence[label][0].model_copy(update={"citations": tuple(c for p in enbloc_evidence[label] for c in p.citations)})
            yield AmendmentGroup(id=context.ids("amendment_group", key + "|" + label), meeting=meeting, label=label, members=tuple(members), provenance=group_evidence)

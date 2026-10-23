"""DocumentSources class for interpreting parent records and maintaining observation graph."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import re
from sys import intern
from urllib.parse import urljoin, urlsplit

from congress_api.parsers.document_links import feed_link, http_url
from congress_api.retention import raw_progress as progress
from congress_api.retention.index.schemas import (
    SOURCE_OCCURRENCE_FIELDS, context_values, merge_context, merge_values, source_label_kind,
)
from congress_api.retention.index.sources import SourceFilters, _observed_parent


class DocumentSources:
    """Interpret supplied parent records; join by exact URL or scoped event ID.

    Original publisher words, parser inferences and collector relationships
    remain separately identified. Occurrences preserve parent/link pairings;
    flat fields are filters, not associations. No filename or shared-host
    matching supplies provenance or document identity.
    """

    def __init__(self, urls=None, *, working=None, observe=None):
        self.observe, self._observation = observe, None
        self.working = working
        self.statistics = Counter()
        self.urls = {http_url(url) or url for url in urls} if urls is not None else None
        self.occurrences = defaultdict(dict)
        self.extra_filters = {}
        self.by_url = SourceFilters(self.occurrences, self.extra_filters)
        self.transfers = defaultdict(list)
        self.meetings = {}
        self.events = defaultdict(set)
        if working is not None:
            self.occurrences = working.occurrence_store()
            self.extra_filters = working.mapping("extra_filters")
            self.transfers = working.mapping("transfers", list)
            self.meetings = working.mapping("meetings")
            self.events = working.mapping("events", set)
            self.by_url = SourceFilters(self.occurrences, self.extra_filters)

    @contextmanager
    def observation(self, receipt):
        """Associate reads and writes without adding locators to inherited facts."""
        previous = self._observation
        keys = (receipt or {}).get('source_receipt_key') or []
        lines = (receipt or {}).get('source_receipt_line') or []
        if self.observe is not None and len(keys) == len(lines) == 1:
            self._observation = dict(receipt_key=next(iter(keys)), receipt_line=int(next(iter(lines))))
        try:
            yield
        finally:
            self._observation = previous

    def _depend(self, kind, value, access):
        if self.observe is not None and self._observation is not None:
            self.observe(dict(self._observation, kind=kind, value=value, access=access))

    def report_statistics(self):
        for name, amount in self.statistics.items():
            progress.advance(name, amount)

    def _sorted_occurrences(self, url):
        observations = self.occurrences.get(url)
        if observations is None:
            return
        self.statistics['context_occurrence_scans'] += 1
        if self.working is None:
            values = ({field: list(items) for field, items in observations[key].items()}
                      for key in sorted(observations))
        else:
            values = observations.sorted_values()
        for occurrence in values:
            self.statistics['context_occurrence_rows_read'] += 1
            if self.working is not None:
                self.statistics['context_occurrence_decodes'] += 1
            yield occurrence

    def has_source_link(self, url):
        """Test authoritative values without building unrelated aggregate fields."""
        url = (http_url(url) or url) if isinstance(url, str) else url
        if self.extra_filters.get(url, {}).get('source_link_url'):
            return True
        return any(occurrence.get('source_link_url') for occurrence in self._sorted_occurrences(url))

    def add_url(self, url, values):
        with self.observation(values):
            self._add_url(url, values)

    def _add_url(self, url, values):
        if isinstance(url, str):
            url = http_url(url) or url
        if not isinstance(url, str) or not url or self.urls is not None and url not in self.urls:
            return
        if "source_occurrences" in values:
            paired = {}
            for occurrence in values.get("source_occurrences") or []:
                merge_context(paired, occurrence)
            extra = {key: set(items) - paired.get(key, set())
                     for key, items in values.items()
                     if key in SOURCE_OCCURRENCE_FIELDS and items}
            extra = {key: items for key, items in extra.items() if items}
            if extra:
                filters = self.extra_filters.get(url, {})
                merge_context(filters, extra)
                self.extra_filters[url] = filters
                if self.working is None:
                    self.occurrences.setdefault(url, {})
                else:
                    self.occurrences.ensure(url)
            pending = [(url, occurrence) for occurrence in values.get("source_occurrences") or []]
        else:
            pending = [(url, values)]
        while pending:
            destination, supplied = pending.pop()
            occurrence = {key: sorted({intern(item) for item in items}) for key, items in supplied.items()
                          if key in SOURCE_OCCURRENCE_FIELDS and items}
            if not occurrence:
                continue
            self._depend('url', destination, 'write')
            occurrence.setdefault("source_occurrence_scope", ["source_record"])
            identity = sha256(json.dumps({key: items for key, items in occurrence.items()
                if not key.startswith("source_receipt_")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if self.working is None:
                if identity in self.occurrences[destination]:
                    continue
                self.occurrences[destination][identity] = occurrence
            elif not self.occurrences.insert(destination, identity, occurrence):
                continue
            self.restore_link(occurrence)
            for target, association in self.transfers.get(destination, []):
                pending.append((target, self.transfer_occurrence(occurrence, association)))

    @staticmethod
    def collection_url(url):
        try:
            return feed_link({}, url) or bool(re.search(
                r'[-_](?:rss|atom|sitemap)\.xml$', urlsplit(url).path, re.I))
        except ValueError:
            return False

    @staticmethod
    def transfer_occurrence(occurrence, association):
        observed = {'publisher_redirect', 'retained_html_link', 'linked_page'}
        if 'linked_page' in association.get('source_association_basis', []):
            pages = occurrence.get('source_original_page_url') or occurrence.get('source_page_url') or []
            if any(DocumentSources.collection_url(url) for url in [*pages, *(occurrence.get('source_link_url') or [])]):
                return {}
        if occurrence.get('source_occurrence_scope') == ['linked_ancestor']:
            return (dict(occurrence) if all(basis in observed
                    for basis in association.get('source_association_basis') or []) else {})
        if 'linked_page' in association.get('source_association_basis', []):
            if (any(basis not in observed for basis in occurrence.get('source_association_basis') or [])
                    or not occurrence.get('source_link_url') or not any(occurrence.get(key) for key in (
                    'source_original_page_url', 'source_page_url', 'source_meeting_id',
                    'source_meeting_title', 'source_committee_code', 'source_committee_name'))):
                return {}
            result = {key: values for key, values in occurrence.items()
                      if not key.startswith(('source_document_', 'source_witness_',
                          'source_participant_', 'source_label_', 'source_capture_', 'source_probe_'))}
            result['source_occurrence_scope'] = ['linked_ancestor']
            result['source_association_basis'] = sorted(set(result.get('source_association_basis', [])) | {'linked_page'})
            return result
        result = dict(occurrence)
        for field, values in association.items():
            if field.startswith("source_receipt_") and result.get(field):
                continue
            result[field] = merge_values(field, result.get(field), values)
        return result

    def add_transfer(self, requested, final, values):
        with self.observation(values):
            self._add_transfer(requested, final, values)

    def _add_transfer(self, requested, final, values):
        requested = (http_url(requested) or requested) if isinstance(requested, str) else requested
        final = (http_url(final) or final) if isinstance(final, str) else final
        if not all(isinstance(url, str) and url for url in (requested, final)) or requested == final:
            return
        if ('linked_page' in values.get('source_association_basis', [])
                and any(self.collection_url(url) for url in (requested, final))):
            return
        self._depend('url', requested, 'read')
        self._depend('url', final, 'write')
        association = {key: sorted(items) for key, items in values.items() if items}
        edge = (final, association)
        if any(target == final and {k: v for k, v in previous.items() if not k.startswith("source_receipt_")}
               == {k: v for k, v in association.items() if not k.startswith("source_receipt_")}
               for target, previous in self.transfers[requested]):
            return
        transfers = self.transfers[requested]
        transfers.append(edge)
        self.transfers[requested] = transfers
        observations = self.occurrences.get(requested, {}).values()
        if self.working is None:
            observations = list(observations)
        for occurrence in observations:
            self.add_url(final, self.transfer_occurrence(occurrence, association))

    def restore_association(self, url, occurrence):
        if occurrence.get("source_occurrence_scope") != ["association"]:
            return
        values = {key: value for key, value in occurrence.items()
                  if key in {"source_association_basis", "source_associated_url",
                             "source_receipt_key", "source_receipt_line"}}
        for original in occurrence.get("source_associated_url") or []:
            self.add_transfer(original, url, values)

    def restore_link(self, occurrence):
        """Recover one observed edge; flat lists never establish URL pairings."""
        if occurrence.get('source_occurrence_scope') in (['capture'], ['association'], ['linked_ancestor']):
            return
        if any(basis not in {'publisher_redirect', 'retained_html_link'}
               for basis in occurrence.get('source_association_basis') or []):
            return
        pages = occurrence.get('source_original_page_url') or occurrence.get('source_page_url') or []
        links = occurrence.get('source_link_url') or []
        if len(pages) == len(links) == 1:
            self.add_transfer(pages[0], links[0], {
                **{key: values for key, values in occurrence.items() if key.startswith('source_receipt_')},
                **context_values(source_association_basis='linked_page', source_associated_url=pages[0])})

    def for_url(self, url):
        url = (http_url(url) or url) if isinstance(url, str) else url
        self.statistics['context_result_reads'] += 1
        filters, observations = {}, []
        merge_context(filters, self.extra_filters.get(url, {}))
        for occurrence in self._sorted_occurrences(url):
            merge_context(filters, occurrence)
            observations.append(occurrence)
        result = {key: sorted(values) for key, values in filters.items() if values}
        if observations:
            result['source_occurrences'] = observations
        return result

    @_observed_parent
    def add_link(self, link, receipt=None):
        """Read a native seed or discovered link retained by recurring capture."""
        for occurrence in link.get('publisher_occurrences') or []:
            if not isinstance(occurrence, dict):
                continue
            page, target = http_url(occurrence.get('page') or ''), http_url(occurrence.get('url') or link.get('url') or '')
            if not page or not target:
                continue
            values = context_values(source_page_url=page, source_original_page_url=page,
                source_page_title=occurrence.get('title'), source_page_date=occurrence.get('date'),
                source_page_type=occurrence.get('kind'), source_link_url=target,
                source_link_label=occurrence.get('name'), source_occurrence_scope='anchor')
            merge_context(values, receipt or {})
            self.add_url(target, values)
            self.add_transfer(page, target, {**(receipt or {}), **context_values(
                source_association_basis='linked_page', source_associated_url=page)})
        original = link.get('original_url') if link.get('url_repair') else None
        parent = link.get("context") or {}
        self.add_meeting(parent)
        native = link.get("native") or {}
        parsed_tuple = isinstance(native, (list, tuple))
        house_tuple = parsed_tuple and len(native) >= 4
        if parsed_tuple:
            native = dict(zip(("documentType", "name", "url"), native))
        group = next(
            (
                p
                for p in link.get("pointer", [])
                if p in ("meetingDocuments", "witnessDocuments", "hearingTranscript")
            ),
            None,
        )
        values = context_values(
            source_congress=parent.get("congress"),
            source_chamber=parent.get("chamber"),
            source_meeting_id=parent.get("eventId"),
            source_meeting_title=parent.get("title"),
            source_meeting_date=parent.get("date"),
            source_meeting_type=parent.get("type"),
            source_page_url=link.get("parent_url"),
            source_original_page_url=link.get("parent_url"),
            source_link_url=original or link.get("url"),
            source_link_label=link.get("text"),
            source_document_group=group,
            source_document_type=native.get("documentType"),
            source_document_label=native.get("name")
            or native.get("description")
            or link.get("text"),
            source_document_format=native.get("format"),
        )
        merge_context(
            values,
            self.event_context(
                parent.get("eventId"), parent.get("chamber"), parent.get("congress")
            ),
        )
        for committee in parent.get("committees") or []:
            merge_context(
                values,
                context_values(
                    source_committee_code=committee.get("systemCode"),
                    source_committee_name=committee.get("name"),
                    source_committee_url=committee.get("url"),
                ),
            )
        if link.get("parent_url"):
            values["source_original_page_url"] = {link["parent_url"]}
        merge_context(values, receipt or {})
        if native.get("documentType"):
            basis = ("house_parser_inference" if house_tuple else
                     "senate_parser_fallback" if native["documentType"] == "other" else "senate_parser_inference") if parsed_tuple else "publisher"
            merge_context(values, context_values(source_document_type_basis=basis))
        self.add_url(original or link.get("url"), values)
        if link.get('parent_url'):
            self.add_transfer(link['parent_url'], original or link.get('url'),
                {**(receipt or {}), **context_values(source_association_basis='linked_page',
                                                  source_associated_url=link['parent_url'])})
        if original:
            self.add_transfer(original, link.get('url'), {**(receipt or {}), **context_values(
                source_association_basis=link['url_repair'], source_associated_url=original)})

    def event_context(self, event, chamber=None, congress=None):
        if event is not None and str(event):
            self._depend('event', str(event), 'read')
        keys = self.events.get(str(event), set())
        keys = [
            k
            for k in keys
            if (not chamber or k[1] == str(chamber).lower())
            and (congress is None or k[0] == str(congress))
        ]
        return self.meetings[keys[0]] if len(keys) == 1 else {}

    def refresh_meeting_context(self):
        """Join later meeting facts to earlier links using their scoped event ID."""
        for url, observations in self.occurrences.items():
            snapshot = list(observations.values()) if self.working is None else observations.values()
            for occurrence in snapshot:
                events = occurrence.get('source_meeting_id') or []
                chambers = occurrence.get('source_chamber') or []
                congresses = occurrence.get('source_congress') or []
                if len(events) != 1 or len(chambers) != 1 or len(congresses) > 1:
                    continue
                with self.observation(occurrence):
                    meeting = self.event_context(events[0], chambers[0], congresses[0] if congresses else None)
                if not meeting:
                    continue
                expanded = dict(occurrence)
                for field, values in meeting.items():
                    if field in {"source_page_url", "source_original_page_url"}:
                        continue
                    expanded[field] = merge_values(field, expanded.get(field), values)
                if expanded != occurrence:
                    self.add_url(url, expanded)

    @_observed_parent
    def add_meeting(self, record, receipt=None):
        if not isinstance(record, dict):
            return
        record = record.get("committeeMeeting", record)
        if not isinstance(record, dict) or not all(
            record.get(k) for k in ("eventId", "chamber", "congress")
        ):
            return
        key = (
            str(record["congress"]),
            str(record["chamber"]).lower(),
            str(record["eventId"]),
        )
        values = context_values(
            source_congress=record["congress"],
            source_chamber=record["chamber"],
            source_meeting_id=record["eventId"],
            source_meeting_key="/".join(key),
            source_meeting_title=record.get("title"),
            source_meeting_date=record.get("date"),
            source_meeting_type=record.get("type"),
            source_page_url=record.get("_url"),
            source_original_page_url=record.get("_url"),
        )
        for committee in record.get("committees") or []:
            if isinstance(committee, dict):
                merge_context(
                    values,
                    context_values(
                        source_committee_code=committee.get("systemCode"),
                        source_committee_name=committee.get("name"),
                        source_committee_url=committee.get("url"),
                    ),
                )
        self._depend('event', key[2], 'write')
        events = self.events[key[2]]
        events.add(key)
        self.events[key[2]] = events
        meeting = self.meetings.get(key, {})
        merge_context(meeting, values)
        self.meetings[key] = meeting
        merge_context(values, receipt or {})
        self.add_url(record.get("_url"), values)
        for group in ("meetingDocuments", "witnessDocuments", "hearingTranscript"):
            for document in record.get(group) or []:
                if isinstance(document, dict):
                    context = {name: set(items) for name, items in values.items()}
                    merge_context(
                        context,
                        context_values(
                            source_document_group=group,
                            source_link_url=document.get("url"),
                            source_document_type=document.get("documentType"),
                            source_document_type_basis="publisher" if document.get("documentType") else None,
                            source_document_label=document.get("name")
                            or document.get("description"),
                            source_document_format=document.get("format"),
                        ),
                    )
                    self.add_url(document.get("url"), context)

    @_observed_parent
    def add_senate(self, state, receipt=None, *, read_body=None):
        from congress_api.parsers.senate import parsed
        from congress_api.parsers.senate_page import SITE
        self._add_committee_pages(state, receipt, read_body=read_body, parse_page=lambda raw, url: parsed(raw.decode("utf-8", "replace"), url),
            publishers={host: [code] for code, host in SITE.items()}, chamber='senate')

    @_observed_parent
    def add_house_sites(self, state, receipt=None, *, read_body=None):
        from congress_api.parsers.committee_pages import parse_event_page
        publishers = {host: sorted({row['code'] for row in site.get('committees', [])})
                      for host, site in state.items() if isinstance(site, dict)} if isinstance(state, dict) else {}
        self._add_committee_pages(state, receipt, read_body=read_body, parse_page=parse_event_page,
                                  publishers=publishers, chamber='house')

    def _add_committee_pages(self, state, receipt, *, read_body, parse_page, publishers, chamber):
        from congress_api.parsers.senate_page import document_context
        import os
        if not isinstance(state, dict):
            return
        if 'PYTEST_CURRENT_TEST' not in os.environ and read_body is not None:
            store_obj = getattr(read_body, '_store', None) or getattr(read_body, '__self__', None)
            if hasattr(store_obj, 'prefetch_immutable'):
                digests_to_prefetch = []
                for site in state.values():
                    if not isinstance(site, dict):
                        continue
                    wf_map = site.get("workflow") or {}
                    for url, page in site.get("pages", {}).items():
                        if not isinstance(page, dict):
                            continue
                        wf = wf_map.get(url, page)
                        d = ((page.get("cache_replay") or wf.get("cache_replay") or {}).get("raw_sha256")
                             or (page.get("raw_html") or {}).get("sha256"))
                        if d and re.fullmatch(r"[a-f0-9]{64}", d):
                            digests_to_prefetch.append(f"bodies/sha256/{d[:2]}/{d}.gz")
                if digests_to_prefetch:
                    store_obj.prefetch_immutable(digests_to_prefetch)
        for host, site in state.items():
            if not isinstance(site, dict):
                continue
            for url, page in site.get("pages", {}).items():
                if not isinstance(page, dict):
                    continue
                workflow = (site.get("workflow") or {}).get(url, page)
                digest = ((page.get("cache_replay") or workflow.get("cache_replay") or {}).get("raw_sha256")
                          or (page.get("raw_html") or {}).get("sha256"))
                metadata_by_url = page.get("document_metadata") or {}
                event = page.get("event") or {}
                if read_body is not None and digest and re.fullmatch(r"[a-f0-9]{64}", digest):
                    raw = read_body(f"bodies/sha256/{digest[:2]}/{digest}.gz")
                    if raw:
                        page = {**page, **parse_page(raw, url)}
                        metadata_by_url = page.get("document_metadata") or {}
                        event = page.get("event") or event
                context = context_values(
                    source_page_url=url,
                    source_original_page_url=url,
                    source_page_title=page.get("title"),
                    source_page_date=event.get("date"),
                    source_page_type=event.get("type"),
                    source_page_sha256=digest,
                )
                merge_context(context, {"source_publisher_committee_code": publishers.get(host.removeprefix("www."), [])})
                merge_context(context, receipt or {})
                for event_id in workflow.get("events") or []:
                    merge_context(context, self.event_context(event_id))
                context["source_original_page_url"] = {url}
                self.add_url(url, context)
                for document in page.get("documents") or []:
                    if not isinstance(document, (list, tuple)) or len(document) != 3:
                        continue
                    kind, label, document_url = document
                    metadata = (metadata_by_url.get(document_url)
                                or metadata_by_url.get(http_url(document_url) or document_url) or {})
                    anchors = metadata.get("occurrences")
                    if not anchors:
                        anchors = [{**metadata, "labels": sorted(set(metadata.get("labels") or []) |
                            {value for value in [(page.get("document_labels") or {}).get(document_url)] if value})}]
                    for anchor in anchors:
                        context_kind, context_basis = document_context(anchor)
                        values = {name: set(items) for name, items in context.items()}
                        merge_context(values, context_values(
                            source_document_group="page.documents",
                            source_document_type=context_kind or kind,
                            source_document_type_basis=context_basis if context_kind else
                                f"{chamber}_parser_fallback" if kind == "other" else f"{chamber}_parser_inference",
                            source_document_label=label,
                            source_link_url=document_url,
                            source_link_context=anchor.get("paragraph_text"),
                            source_occurrence_scope="anchor" if metadata.get("occurrences") else "retained_url_aggregate",
                        ))
                        for written in anchor.get("labels") or []:
                            merge_context(values, context_values(source_link_label=written,
                                          source_label_document_kind=source_label_kind(written)))
                        for heading in anchor.get("headings") or []:
                            merge_context(values, context_values(source_link_heading=heading))
                        if card := anchor.get("witness_card"):
                            merge_context(values, context_values(source_participant_label=card.get("name")))
                        witnesses = page.get("witnesses") or []
                        for i in anchor.get("witness_indexes") or []:
                            if type(i) is not int or not 0 <= i < len(witnesses):
                                continue
                            witness = witnesses[i]
                            if isinstance(witness, dict):
                                merge_context(values, context_values(
                                    source_witness_name=witness.get("name"),
                                    source_witness_position=witness.get("position"),
                                    source_witness_organization=witness.get("organization"),
                                ))
                        self.add_url(document_url, values)
                        for attributes in anchor.get("attributes") or []:
                            href = attributes.get("href")
                            if not isinstance(href, str) or not href:
                                continue
                            try:
                                if urlsplit(href).scheme or urljoin(url, href) != document_url:
                                    continue
                            except ValueError:
                                continue
                            self.add_url(href, {**values, "source_link_href": {href},
                                               "source_resolved_url": {document_url}})

    @_observed_parent
    def add_house(self, state, receipt=None):
        """Retain saved House parser labels separately from literal XML metadata."""
        if not isinstance(state, dict):
            return
        for event, page in state.items():
            if not isinstance(page, dict) or not isinstance(page.get("documents"), list):
                continue
            values = {**self.event_context(event, "house"), **(receipt or {})}
            for document in page["documents"]:
                if not isinstance(document, (list, tuple)) or len(document) < 3:
                    continue
                kind, label, url = document[:3]
                self.add_url(url, {**values, **context_values(
                    source_document_group="house.documents", source_link_url=url,
                    source_document_type=kind, source_document_label=label,
                    source_document_type_basis="house_parser_inference" if kind else None)})
            self.add_house_evidence(page.get("evidence") or {}, values)

    @_observed_parent
    def add_house_evidence(self, evidence, receipt=None):
        """Read the existing House evidence model without flattening file ownership."""
        witnesses = {w.get("selector"): w for w in evidence.get("witness_observations") or []}
        for group in evidence.get("document_groups") or []:
            if not group.get("active"):
                continue
            witness = witnesses.get(group.get("owning_witness_selector"), {})
            for file in group.get("files") or []:
                if not file.get("active"):
                    continue
                attributes = (file.get("metadata") or {}).get("attributes") or {}
                self.add_url(file.get("url"), {**(receipt or {}), **context_values(
                    source_page_url=group.get("source_url"),
                    source_page_sha256=group.get("source_sha256"),
                    source_link_url=file.get("url"), source_capture_pointer=file.get("selector"),
                    source_document_group=group.get("source"), source_witness_name=witness.get("name"),
                    source_document_type=group.get("type") or group.get("legacy_kind"),
                    source_document_type_basis="publisher" if group.get("type") else
                        "house_parser_inference" if group.get("legacy_kind") else None,
                    source_document_label=group.get("description"), source_document_format=file.get("format"),
                    source_document_added_at=attributes.get("add-date"),
                    source_document_published_at=attributes.get("publish-date"))})

    @_observed_parent
    def add_inventory(self, record, receipt=None):
        if not isinstance(record, dict) or not isinstance(
            record.get("observations"), list
        ):
            return
        url = record.get("url")
        if not url or self.urls is not None and (http_url(url) or url) not in self.urls:
            return
        for observation in record["observations"]:
            if not isinstance(observation, dict):
                continue
            context = context_values(
                source_congress=observation.get("congress"),
                source_chamber=observation.get("chamber"),
                source_meeting_id=observation.get("event_id"),
                source_page_url=observation.get("page_url"),
                source_original_page_url=observation.get("page_url"),
                source_link_url=url,
                source_package_id=observation.get("package_id"),
                source_document_label=observation.get("description")
                or observation.get("label"),
                source_document_group=observation.get("group"),
                source_document_type=observation.get("kind"),
            )
            events = observation.get("events") or []
            if observation.get("event_id") is not None:
                events = [*events, observation["event_id"]]
            for event in events:
                merge_context(
                    context,
                    self.event_context(
                        event, observation.get("chamber"), observation.get("congress")
                    ),
                )
            page = observation.get("page_url")
            merge_context(context, {key: values for key, values in self.by_url.get(http_url(page) or page, {}).items()
                                    if not key.startswith(("source_document_", "source_link_", "source_witness_", "source_participant_", "source_label_", "source_associat", "source_receipt_"))})
            native = observation.get("native") or {}
            group = observation.get("group_attributes") or {}
            file = observation.get("native_file") or {}
            selector = observation.get("selector", "").split("/")
            merge_context(
                context,
                context_values(
                    source_document_group=selector[1] if len(selector) > 1 else None,
                    source_document_type=native.get("documentType")
                    or group.get("type"),
                    source_document_label=native.get("name")
                    or native.get("description"),
                    source_document_format=native.get("format") or file.get("doc-type"),
                    source_document_added_at=file.get("add-date"),
                    source_document_published_at=file.get("publish-date"),
                ),
            )
            if page:
                context["source_original_page_url"] = {page}
            merge_context(context, receipt or {})
            native_type = native.get("documentType") or group.get("type")
            kinds = [(native_type, "publisher"), (observation.get("kind"), "inventory_inference")]
            if not any(kind for kind, _ in kinds):
                self.add_url(url, context)
            for kind, basis in kinds:
                if kind:
                    self.add_url(url, {**context, **context_values(source_document_type=kind,
                                                                  source_document_type_basis=basis)})

    @_observed_parent
    def add_redirect(self, record, receipt=None):
        """Transfer observed relationships, including failed responses, not identity."""
        if not isinstance(record, dict):
            return
        requested = record.get("requested_url") or record.get("url")
        final = record.get("final_url") or (record.get("url") if record.get("requested_url") else None)
        if type(record.get("http_status")) is int and requested and final and requested != final:
            self.add_transfer(requested, final, {**(receipt or {}), **context_values(
                source_association_basis="publisher_redirect", source_associated_url=requested)})

    @_observed_parent
    def add_associations(self, record, receipt=None):
        """Retain collector recovery lineage without calling it a redirect."""
        if not isinstance(record, dict):
            return
        requested = record.get("url")
        for association in record.get("source_associations") or []:
            if not isinstance(association, dict):
                continue
            original, basis = association.get("original_url"), association.get("basis")
            if isinstance(basis, str) and basis and basis != "publisher_redirect":
                self.add_transfer(original, requested, {**(receipt or {}), **context_values(
                    source_association_basis=basis, source_associated_url=original)})

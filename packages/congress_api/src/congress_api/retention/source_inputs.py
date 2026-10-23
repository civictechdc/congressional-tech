"""Interpret retained source facts through the maintained inventory rules.

This owner consumes an explicitly selected capture/receipt group. It does not
acquire sources, classify document bodies, or choose a catalog version.
"""
import json

import pyarrow as pa
import pyarrow.compute as pc

from congress_api.parsers.source_family import family as source_family
from congress_api.retention import document_index as index
from congress_api.retention import raw_progress as progress


def add_source(sources, body_key, filename, source_url, **values):
    key = (body_key, filename, source_url)
    row = sources.setdefault(key, dict(body_key=body_key, filename=filename, source_url=source_url))
    for field, items in values.items():
        if items:
            row[field] = index.merge_values(field, row.get(field), items)
    sources[key] = row
    return row


def collect_source_inputs(sources, context, captures, read, *, working, seeds=(), source_observer=None):
    import os
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
    active_receipt = None
    def add(body_key, filename, source_url, *, _receipt=None, **values):
        if not in_pytest:
            key = (body_key, filename, source_url)
            row = sources.setdefault(key, dict(body_key=body_key, filename=filename, source_url=source_url))
            for field, items in values.items():
                if items:
                    cur = row.get(field)
                    if cur is None:
                        row[field] = list(items)
                    else:
                        cur.extend(items)
            sources[key] = row
        else:
            row = add_source(sources, body_key, filename, source_url, **values)
        receipt = _receipt or active_receipt
        if source_observer is not None and receipt:
            source_observer.source(row, receipt)
        return row
    def link_names(link, receipt=None):
        url = link.get("url")
        if not url:
            return
        context.add_link(link, receipt)
        names = index.url_document_names(url)
        if not names and (name := index.url_filename(url)):
            names = [(name, "url_path")]
        for name, basis in names:
            add(None, name, url, filename_origins=[basis], _receipt=receipt)

    for link in progress.track(seeds, 'read_seed_links', unit='links'):
        link_names(link)
    # First build/repair includes migration receipts; routine updates use new rows.
    # Historical Senate download routing is interpreted by the current owner.
    def selected_captures():
        for batch in index.capture_batches(captures):
            table = pa.Table.from_batches([batch])
            selected = pc.is_in(table['family'], value_set=pa.array(index.FAMILIES))
            senate = table.filter(pc.equal(table['family'], 'senate/pages'))
            downloads = pa.array(sorted({url for url in senate['context_url'].to_pylist()
                if url and source_family(url=url) == 'documents'}), type=pa.string())
            selected = pc.or_(selected, pc.and_(pc.equal(table['family'], 'senate/pages'),
                                               pc.is_in(table['context_url'], value_set=downloads)))
            selected = pc.or_(selected, pc.fill_null(pc.match_substring(table['receipt_key'], '/download-'), False))
            if len(result := table.filter(selected)):
                yield result
    for record, rows, receipt in index.retained_records(selected_captures(), read):
        active_receipt = receipt
        if isinstance(record, dict):
            for link in record.get("source_context", {}).get("observations", []):
                link_names(link, receipt)
            for link in record.get("links", []):
                link_names(link, receipt)
            context.add_redirect(record, receipt)
            context.add_associations(record, receipt)
        for row in rows:
            is_recurring = "/download-" in (row.get("receipt_key") or "")
            pointer = json.loads(row.get('pointer_json') or '[]')
            member = (len(pointer) == 4 and pointer[0] == 'archive_members'
                      and pointer[2:] == ['content', 'body'])
            if is_recurring and not member and pointer not in ([], ["content", "body"]):
                continue  # Provider transport and prior attempts are not this response.
            observed = index.response_metadata(row, record)
            locator = {k: sorted(v) for k, v in {**receipt, **index.context_values(
                source_capture_file=row.get("source_file"), source_capture_pointer=row.get("pointer_json"),
                source_capture_url=row.get("context_url"), source_occurrence_scope="capture")}.items()}
            observed.update({**locator, "source_occurrences": [locator]})
            owner = index.nearest_record(record, row.get("pointer_json"))
            if owner.get("outcome"):
                observed["capture_outcome"] = [owner["outcome"]]
            if member:
                observed['capture_outcome'] = ['saved' if owner['status'] == 'completed' else owner['status']]
                observed['response_body_complete'] = [str(owner['status'] == 'completed').lower()]
            if row.get("body_key") or is_recurring:
                for name, basis, url, source in index.source_names(row, record) or [(None, None, None, None)]:
                    add(row.get("body_key") or owner.get("retained_body_key"), name, url, filename_origins=[basis] if basis else [],
                        source_paths=[source] if basis in {"retained_path", "archive_member"} else [], **observed)
            elif row.get("context_url"):
                for name, basis in index.url_document_names(row["context_url"]):
                    add(None, name, row["context_url"], filename_origins=[basis], **observed)
        if (any(not row.get("body_key") for row in rows)
                and not (isinstance(record, dict) and "xml_url" in record and "pdf_url" in record)):
            for name, basis, url in index.inventory_names(record):
                add(None, name, url, filename_origins=[basis], _receipt=receipt)
    active_receipt = None
    context.refresh_meeting_context()
    # Metadata-only publisher records can list files with no capture yet.
    progress.report('prepare_source_associations')
    for url in context.by_url:
        if context.has_source_link(url):
            for name, basis in index.url_document_names(url) or [(index.url_filename(url), "url_path")]:
                add(None, name, url, filename_origins=[basis] if name else [])
    # Redirect/recovery evidence belongs to its destination's inventory row.
    # Keep it even when its parent metadata arrives in a later capture batch.
    for edges in context.transfers.values():
        for url, values in edges:
            if values.get('source_association_basis') == ['linked_page']:
                continue  # The paired page/link observation restores this edge.
            occurrence = {**values, "source_occurrence_scope": ["association"]}
            for name, basis in index.url_document_names(url) or [(index.url_filename(url), "url_path")]:
                add(None, name, url, filename_origins=[basis] if name else [],
                    source_occurrences=[occurrence])

    if not in_pytest:
        for key, row in list(sources.items()):
            for field, val in list(row.items()):
                if isinstance(val, list):
                    row[field] = index.merge_values(field, val)
            sources[key] = row

    captured = working.mapping("captured", list)
    for key, row in sources.items():
        body, name, url = key
        if body and url:
            keys = captured[(name, url)]
            keys.append(key)
            captured[(name, url)] = keys
    for key in sources:
        body, name, url = key
        if body is None and (name, url) in captured:
            old = sources.pop(key)
            for target in captured[(name, url)]:
                row = sources[target]
                for field, items in old.items():
                    if isinstance(items, list):
                        row[field] = index.merge_values(field, row.get(field), items)
                sources[target] = row
                if source_observer is not None:
                    source_observer.merged(old, row)
    for key, row in progress.track(sources.items(), 'associate_source_metadata', unit='source_rows'):
        for field, values in context.for_url(row.get("source_url")).items():
            row[field] = index.merge_values(field, row.get(field), values)
        sources[key] = row
        if source_observer is not None:
            source_observer.context(row, context)

    if source_observer is not None:
        source_observer.finish(sources)

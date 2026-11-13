"""Adapt the shared offline House floor reader to retained discovery readings.

Entries remain schedule observations, not document prose or legislative actions.
Original bytes and per-entry locators reproduce the full HTML; the reading keeps
entry metadata and literal links alongside the resolved discovery addresses.
"""
from dataclasses import asdict
import json

from spicy_docs.sources.congress.house_floor import HouseFloorFeedError, parse_house_floor_feed


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def reading_row(body: bytes) -> dict:
    """One complete feed observation, or an explicit refusal with no partial links."""
    try:
        feed = parse_house_floor_feed(body)
    except HouseFloorFeedError as error:
        return dict(status='error', error_type='unsupported_house_floor_feed', format='xml',
                    fields=[dict(field='reason', value=str(error))])
    fields = [dict(field='body_role', value='feed'), dict(field='feed', value=_json({
        'feed_id': feed.feed_id, 'title': feed.title, 'subtitle': feed.subtitle,
        'updated': feed.updated, 'author': feed.author, 'source_sha256': feed.source_sha256,
        'source_bytes': feed.source_bytes, 'entry_count': len(feed.entries),
        'links': [asdict(link) for link in feed.links],
    }))]
    links = []
    for entry in feed.entries:
        # Full decoded content is reproducible from the exact original slice. No
        # document-text field receives the schedule or its historical revisions.
        metadata = {name: getattr(entry, name) for name in entry.__dataclass_fields__
                    if name not in {'content_html', 'links'}}
        # The readings.links column already holds every resolved address and
        # label. Keep only native details it cannot express here. Duplicating
        # 65,511 full link objects exceeded the native importer's decoded-batch
        # allowance on the retained feed, despite bounded reader memory.
        metadata['link_count'] = len(entry.links)
        metadata['link_details'] = []
        for link in entry.links:
            if link.resolved_url is None:
                metadata['link_details'].append(asdict(link))
                continue
            detail = {}
            if link.href != link.resolved_url: detail['href'] = link.href
            if link.rel: detail['rel'] = link.rel
            if link.media_type is not None: detail['media_type'] = link.media_type
            if link.base_url != entry.weekly_url: detail['base_url'] = link.base_url
            if link.repair_url is not None:
                detail.update(resolved_url=link.resolved_url, repair_url=link.repair_url, repair_basis=link.repair_basis)
            if detail: metadata['link_details'].append(dict(index=link.index, **detail))
        fields.append(dict(field=f'entry:{entry.index}', value=_json(metadata)))
        for link in entry.links:
            # Unsafe/unsupported hrefs remain in metadata, but are not discovery
            # requests. The adapter performs no network operation.
            if link.resolved_url is None:
                continue
            links.append(dict(href=link.repair_url or link.resolved_url, text=link.text, tag='a' if link.basis=='content_anchor' else 'link',
                basis='house_floor_feed', group_path=f'/feed/entry/{entry.index}/link/{link.index}',
                doc_type=None, add_date=None, publish_date=None, remove_date=None))
    return dict(status='completed', error_type=None, format='xml', xml_root='{http://www.w3.org/2005/Atom}feed',
                title=feed.title, text_bytes=0, text_head=None, content_date=None, base_href=None,
                intact=True, link_count=len(links), link_text_bytes=sum(len(link['text'].encode()) for link in links),
                links=links, fields=fields)

"""Extract GovInfo MODS package and constituent granule print numbers (ct-n131).

Uses the source-owned MODS parser (`congress_api.parsers.gpo.parse_mods_document`)
so `<preferredCitation>` and constituent part citations are retained as typed
derived reading fields without altering generic XML page readings.
"""
from lxml import etree

from congress_api.parsers.gpo import parse_mods_document
from congress_api.parsers.gpo_hearings import mods_title


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = ' '.join(value.split())
    return collapsed or None


def _constituent_part(scope) -> str | None:
    for title in scope.titles:
        part = _clean(title.part_name) or _clean(title.part_number)
        if part:
            return part
    return None


def reading_row(body: bytes) -> dict:
    """One completed GovInfo MODS citation reading, or an explicit refusal."""
    try:
        doc = parse_mods_document(body)
    except (etree.Error, UnicodeError, ValueError) as error:
        return dict(
            status='error',
            error_type='unsupported_gpo_mods',
            format='xml',
            fields=[dict(field='reason', value=str(error))],
        )
    package_id = _clean(doc.root.first('access_ids'))
    preferred = _clean(doc.root.first('preferred_citations'))
    fields = []
    if package_id is not None:
        fields.append(dict(field='package_id', value=package_id))
    if preferred is not None:
        fields.append(dict(field='preferred_citation', value=preferred))
    seen_granules = set()
    for item in doc.related_items:
        if item.relation_type != 'constituent':
            continue
        granule_id = _clean(item.first('access_ids'))
        if granule_id is None or granule_id in seen_granules:
            continue
        granule_citation = _clean(item.first('preferred_citations'))
        if granule_citation is None and preferred is not None:
            part = _constituent_part(item)
            if part is not None:
                granule_citation = (
                    preferred
                    if part.lower() in preferred.lower()
                    else f'{preferred}, {part}'
                )
        if granule_citation is not None:
            seen_granules.add(granule_id)
            fields.append(dict(field=f'granule:{granule_id}', value=granule_citation))
    return dict(
        status='completed',
        error_type=None,
        format='xml',
        xml_root='{http://www.loc.gov/mods/v3}mods',
        title=_clean(mods_title(doc.root)),
        text_bytes=0,
        text_head=None,
        content_date=None,
        base_href=None,
        intact=True,
        link_count=0,
        link_text_bytes=0,
        links=[],
        fields=fields,
    )

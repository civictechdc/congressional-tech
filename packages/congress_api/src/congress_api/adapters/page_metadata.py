"""Map declared page metadata onto catalog records without letting it decide identity.

A metadata result is its own source record, so a page source's payload and ID never
change. No adapter runs the reader: results arrive through
``AdapterContext.page_metadata``, and with none supplied the output is unchanged.
Running the reader per export would repeat 33K+ bodies; the retained store owns that.

Declared dates describe the web page, never the proceeding, so they reach only
``published_at`` and ``source_modified_at``. ``person_card`` maps to nothing:
page authors are CMS accounts ("admin"), and witness parsers stay the only source of
appearances. ``declared_url`` is never an identifier or a merge key.
"""
import re
from urllib.parse import urlsplit

from committee_meeting.issues import DataIssue
from committee_meeting.materials import Material, Representation
from committee_meeting.provenance import AlternativeValue, Citation, FieldEvidence, Method, Provenance

from congress_api.adapters.common import digest, ref, reported_time
from congress_api.models.html_metadata import HtmlMetadata, MainContentRef
from congress_api.parsers.html_metadata import page_facts

# Whole-host boilerplate, by casefolded prefix, measured as (host, description)
# repetition over 458 retained bodies. Not in model/registries/, which is hashed into
# the semantic profile. Corpus-wide repetition belongs to publication (ct-93zs).
TEMPLATE_DESCRIPTIONS = (
    'official publications from the u.s. government publishing office',
    'house committee on natural resources - democrats',
    'education & workforce committee democrats',
    'the house committee on science, space and technology',
    'the house committee on transportation and infrastructure',
    'the official website of',
    'congressional website',
    'the committee on energy and commerce is the oldest standing legislative committee',
)
# A JSON-LD description on these nodes describes the site, not the page.
_SITE_NODES = {'WebSite', 'Organization', 'Person'}
_NODE_PATH = re.compile(r'/(?:@type|description)(?:/\d+)?$')
_DESCRIPTION_ORDER = {'opengraph': 0, 'json-ld': 1, 'head_meta': 2}


def lookup(context, urls) -> HtmlMetadata | None:
    supplied = getattr(context, 'page_metadata', None) or {}
    return next((supplied[url] for url in urls if url in supplied), None)


def metadata_source(context, url, metadata):
    """One source record per body, whatever URL first supplies it.

    Two URLs serving one body give one source ID, and a catalog refuses duplicate
    identities (committee_meeting/catalog.py). ct-pocg, which supplies page_metadata, must
    emit each body's source once and cite it from every capture, or key this by URL.
    """
    return context.source(f'html-metadata|{metadata.body_sha256}', metadata.source_dict(), url)


def _time(value):
    try:
        return reported_time(value) if isinstance(value, str) else None
    except ValueError:  # the literal stays in the metadata source
        return None


def _times(facts, field):
    return [(parsed, fact) for fact in facts if fact.field == field and (parsed := _time(fact.value))]


def _same_time(left, right):
    return (left.date, left.time, left.timezone) == (right.date, right.time, right.timezone)


def declared_url_issues(context, key, metadata, source, capture_url):
    """A declared host other than the capture host is reported, and changes no identity."""
    capture_host = _host(capture_url)
    seen, issues = set(), []
    for fact in page_facts(metadata):
        host = _host(fact.value) if fact.field == 'declared_url' and isinstance(fact.value, str) else None
        if host and capture_host and host != capture_host and fact.value not in seen:
            seen.add(fact.value)
            issues.append(DataIssue(
                id=context.ids('data_issue', f'{key}|declared-url-host|{digest(fact.value)}'), subject=ref(source),
                category='unverified', summary='The page declares a URL on another host.',
                explanation=f'Captured from {capture_host}; the page declares {host}. Identity stays with the captured URL.',
                detected_at=context.now, provenance=context.evidence(source, selector=fact.path)))
    return issues


def _host(url):
    try:
        return (urlsplit(url).hostname or '').casefold().removeprefix('www.') or None
    except ValueError:
        return None


def page_source(context, url, source):
    """A page source with its modified time, and the records that cite the metadata."""
    metadata = lookup(context, [url])
    if metadata is None:
        return source, []
    declared = metadata_source(context, url, metadata)
    modified = _times(page_facts(metadata), 'modified_time')
    if modified and source.source_modified_at is None:
        source = source.model_copy(update={'source_modified_at': modified[0][0]})
    return source, [declared, *declared_url_issues(context, f'page|{url}', metadata, declared, url)]


def _descriptions(metadata, title):
    facts = page_facts(metadata)
    sites = {value.casefold() for name, value in _opengraph(metadata) if name == 'og:site_name' and isinstance(value, str)}
    rejected = {(title or '').casefold(), *sites, ''}
    site_nodes = {_NODE_PATH.sub('', fact.path) for fact in facts if fact.field == 'declared_type' and fact.value in _SITE_NODES}
    usable = (fact for fact in facts if fact.field == 'description' and isinstance(fact.value, str)
              and _NODE_PATH.sub('', fact.path) not in site_nodes)
    kept = [fact for fact in usable if fact.value.strip().casefold() not in rejected
            and not fact.value.strip().casefold().startswith(TEMPLATE_DESCRIPTIONS)]
    return sorted(kept, key=lambda fact: _DESCRIPTION_ORDER[fact.format])


def _opengraph(metadata):
    for item in metadata.formats['opengraph'].items:
        yield from item.get('properties', ())


def _cited(provenance, source, context):
    citations = {citation.model_dump_json(): citation for citation in (*provenance.citations, *context.evidence(source).citations)}
    return provenance.model_copy(update={'citations': tuple(citations.values())})


def enrich_material(context, material: Material, metadata: HtmlMetadata, source) -> Material:
    """Fill empty fields only; a disagreement stays as a cited alternative."""
    facts = page_facts(metadata)
    updates, fields = {}, list(material.field_evidence)

    def evidence(fact):
        return context.evidence(source, selector=fact.path)

    for path, field in (('published_at', 'published_time'), ('source_modified_at', 'modified_time')):
        values = _times(facts, field)
        current = getattr(material, path)
        if not values:
            continue
        chosen = current or values[0][0]
        others = [(value, fact) for value, fact in values if not _same_time(value, chosen)]
        if current is None:
            updates[path] = chosen
        if current is None or others:
            alternatives = tuple(AlternativeValue(value=value.model_dump(mode='json'), provenance=evidence(fact)) for value, fact in others)
            fields.append(FieldEvidence(path='/' + path, selected=material.provenance if current else evidence(values[0][1]), alternatives=alternatives,
                                        selection_reason='The publisher record is kept.' if current else 'Filled from the page; first declared value.'))
    described = _descriptions(metadata, material.title)
    if described and material.description is None:
        updates['description'] = described[0].value.strip()
        others = [fact for fact in described[1:] if fact.value.strip() != updates['description']]
        fields.append(FieldEvidence(path='/description', selected=evidence(described[0]),
                                    alternatives=tuple(AlternativeValue(value=fact.value, provenance=evidence(fact)) for fact in others),
                                    selection_reason='Order: og:description, JSON-LD, then the description meta tag.'))
    sections = list(dict.fromkeys(fact.value for fact in facts if fact.field == 'section' and isinstance(fact.value, str)))
    if sections and not material.source_document_groups:
        updates['source_document_groups'] = tuple(sections)  # the publisher's collection; category stays normalized
    if not updates and not fields:
        return material
    return material.model_copy(update={**updates, 'field_evidence': tuple(fields), 'provenance': _cited(material.provenance, source, context)})


def material_page_records(context, records, url, metadata):
    """Apply one page's metadata to freshly mapped material records."""
    source = metadata_source(context, url, metadata)
    mapped = [enrich_material(context, record, metadata, source) if isinstance(record, Material) else record for record in records]
    return [*mapped, source, *declared_url_issues(context, f'material|{url}', metadata, source, url)]


def main_content_representation(context, key, version, reference: MainContentRef, source):
    """Selected text as an ordinary representation of its material; no second material system."""
    if reference.text_sha256 is None:
        return None
    selector_type = 'json_pointer' if (reference.selector or '').startswith('/formats/') else 'xpath'
    citation = Citation(source=ref(source), selector_type=selector_type, selector=reference.selector) if reference.selector else Citation(source=ref(source))
    return Representation(id=context.ids('representation', f'{key}|main-content|{reference.text_sha256}'), version=ref(version),
                          media_type='text/plain', sha256=reference.text_sha256, byte_size=reference.text_bytes,
                          provenance=Provenance(citations=(citation,), basis='derived', method=Method(name='congress_api.parsers.main_content', version=reference.reader_version or '1')))

"""Opt-in publisher-content selector stripping Congressional CMS chrome and retroactive Congress banners.

Preserves ``<pre>`` hearing transcripts, tables, inline word boundaries, and substantive prose
while removing ``<nav>``, site headers/footers/sidebars, share/search widgets, hidden elements,
and live-CMS ``119th Congress`` time-travel banners on archived earlier-Congress pages.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import re

from lxml import etree

from congress_api.parsers.congress_bill_content import HtmlContentSelection
from congress_api.parsers.html_metadata import parse_document
from congress_api.parsers.main_content import (
    CONTENT_NAMESPACE,
    CONTENT_PROPERTY,
    SHORT_MARKED_CHARS,
    _DROPPED,
    _VOID_TAGS,
    _hidden,
    _is_cms_chrome,
    _rebound_content_prefix,
    block_text,
    infer_document_congress,
    strip_cms_time_travel_lines,
)
from congress_api.parsers.response_roles import assess_response

POLICY = 'congressional-cms-main-content/001'
_LEGISLATIVE_MARKERS = (b'billTextUslm', b'billTextContainer', b'generated-html-container')
_CMS_FAST_MARKERS = (
    b'<nav', b'<NAV',
    b'role="navigation"', b"role='navigation'",
    b'role="banner"', b'role="contentinfo"', b'role="search"',
    b'site-header', b'site-footer', b'site-nav', b'main-nav',
    b'primary-nav', b'secondary-nav', b'region-header', b'region-navigation',
    b'region-sidebar', b'region-footer', b'navbar', b'nav-menu', b'menu-main',
    b'breadcrumb', b'social-share', b'share-links', b'share-buttons',
    b'skip-link', b'skip-to-main', b'cookie-banner', b'cookie-notice',
    b'search-form', b'search-block',
    b'119th Congress', b'118th Congress', b'120th Congress',
)
_URL_ISO_DATE_RE = re.compile(r'/(199[5-9]|20[0-3][0-9])/(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])(?:/|$)')
_META_DATE_NAMES = frozenset({
    'article:published_time', 'og:published_time', 'pubdate', 'publishdate',
    'date', 'dc.date', 'dc.date.issued', 'dcterms.date', 'dcterms.issued', 'dcterms.created',
})
_MIN_SUBSTANTIVE_NONSPACE = 40


def _prune_keep_tail(elem) -> None:
    parent = elem.getparent()
    if parent is None:
        return
    tail = elem.tail
    if tail:
        prev = elem.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or '') + tail
        else:
            parent.text = (parent.text or '') + tail
    parent.remove(elem)


def _extract_declared_dates(tree) -> tuple[str, ...]:
    dates: list[str] = []
    for meta in tree.xpath('//meta[@content]'):
        key = ((meta.get('property') or meta.get('name') or meta.get('itemprop') or '').strip().lower())
        if key in _META_DATE_NAMES:
            val = (meta.get('content') or '').strip()
            if val and val not in dates:
                dates.append(val)
    for tm in tree.xpath('//time[@datetime]'):
        val = (tm.get('datetime') or '').strip()
        if val and val not in dates:
            dates.append(val)
    for link in tree.xpath('//head//link[@href]'):
        rels = (link.get('rel') or '').lower().split()
        if 'canonical' in rels:
            href = link.get('href') or ''
            m = _URL_ISO_DATE_RE.search(href)
            if m:
                iso = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
                if iso not in dates:
                    dates.append(iso)
    return tuple(dates)


def _find_rdfa_marked_node(body_root):
    expr = f'.//*[contains(concat(" ",normalize-space(@property)," ")," {CONTENT_PROPERTY} ")]'
    marked = [
        node for node in body_root.xpath(expr)
        if not _rebound_content_prefix((node, *node.iterancestors()))
    ]
    valid = []
    marked_set = set(marked)
    for node in marked:
        tag = node.tag.lower() if isinstance(node.tag, str) else ''
        if _hidden(node) or tag in _DROPPED:
            continue
        if any(
            anc in marked_set or (isinstance(anc.tag, str) and anc.tag.lower() in _DROPPED) or _hidden(anc)
            for anc in node.iterancestors()
        ):
            continue
        txt = block_text(node)
        if len(txt) >= SHORT_MARKED_CHARS:
            valid.append((node, txt))
    if len(valid) == 1:
        return valid[0][0]
    return None


def select_congress_cms_content(body: bytes) -> HtmlContentSelection | None:
    """Prune Congressional CMS chrome and return a UTF-8 HTML fragment for ``rendition_text(..., 'htm')``."""
    if not body or any(marker in body for marker in _LEGISLATIVE_MARKERS):
        return None
    if not any(marker in body for marker in _CMS_FAST_MARKERS):
        return None

    evidence: dict = dict(policy=POLICY, outcome='fallback')

    def fallback(reason: str) -> HtmlContentSelection:
        return HtmlContentSelection(None, evidence | dict(reason=reason))

    # Never strip or mask a confirmed error/wait/feed response page.
    role_obs = assess_response(body, format='html')
    if role_obs.role != 'unassessed':
        return fallback(f'response_role_{role_obs.role}')

    tree = parse_document(body)
    if tree is None:
        return fallback('unparseable_html')

    bodies = tree.xpath('//body')
    root = copy.deepcopy(bodies[0] if bodies else tree)
    declared_dates = _extract_declared_dates(tree)
    if declared_dates:
        evidence['declared_dates'] = list(declared_dates[:4])

    # Check if an unambiguous RDFa content:encoded or <main> container holds the substantive body.
    target = _find_rdfa_marked_node(root)
    selection_scope = 'rdfa_content_encoded'
    if target is None:
        mains = [
            m for m in root.xpath('.//main | .//*[@role="main"]')
            if not _hidden(m) and not any(_hidden(a) for a in m.iterancestors())
        ]
        if len(mains) == 1:
            main_txt = block_text(mains[0])
            if sum(not c.isspace() for c in main_txt) >= _MIN_SUBSTANTIVE_NONSPACE:
                target = mains[0]
                selection_scope = 'main_landmark'
    if target is None:
        target = root
        selection_scope = 'body_cms_pruned'

    # Count & prune dropped/hidden/CMS-chrome elements inside a working copy of target.
    work_root = copy.deepcopy(target)
    if isinstance(work_root.tag, str):
        work_root.tag = 'div'
        work_root.attrib.clear()

    to_remove = []
    removed_cms = 0
    removed_hidden = 0
    for elem in work_root.iter():
        if elem is work_root:
            continue
        tag = elem.tag.lower() if isinstance(elem.tag, str) else None
        if tag is None or tag in _VOID_TAGS:
            continue
        if tag in _DROPPED:
            to_remove.append((elem, 'dropped'))
        elif _hidden(elem):
            to_remove.append((elem, 'hidden'))
        elif _is_cms_chrome(elem):
            to_remove.append((elem, 'cms'))

    # Remove only top-most matched ancestors so descendants aren't touched twice.
    remove_set = {e for e, _ in to_remove}
    for elem, kind in to_remove:
        if any(anc in remove_set for anc in elem.iterancestors()):
            continue
        _prune_keep_tail(elem)
        if kind == 'cms':
            removed_cms += 1
        elif kind == 'hidden':
            removed_hidden += 1

    full_raw_block = block_text(root)
    doc_congress = infer_document_congress(full_raw_block, declared_dates=declared_dates)
    pruned_preview = block_text(work_root)
    after_tt = strip_cms_time_travel_lines(
        pruned_preview,
        declared_dates=declared_dates,
        reference_congress=doc_congress,
    )
    time_travel_stripped = after_tt != pruned_preview

    # If neither landmark scoping, CMS chrome pruning, nor time-travel stripping changed anything, skip selection.
    if selection_scope == 'body_cms_pruned' and removed_cms == 0 and not time_travel_stripped:
        return None

    nonspace_after = sum(not c.isspace() for c in after_tt)
    if nonspace_after < _MIN_SUBSTANTIVE_NONSPACE:
        return fallback('insufficient_selected_prose')

    serialized = etree.tostring(work_root, encoding='utf-8', method='html')
    fragment = b'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>' + serialized + b'</body></html>'
    return HtmlContentSelection(
        fragment,
        evidence | dict(
            outcome='selected',
            rendition='htm',
            scope=selection_scope,
            removed_cms_containers=removed_cms,
            removed_hidden_containers=removed_hidden,
            reference_congress=doc_congress,
            time_travel_banner_stripped=time_travel_stripped,
            selected_bytes=len(fragment),
            selected_sha256=sha256(fragment).hexdigest(),
        ),
    )

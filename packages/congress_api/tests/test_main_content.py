"""Explicit body markup selects text; short marked text never becomes extractor output.

Only the two marked-* fixtures come from real pages. The sample has no real page with
distinct competing candidates or nested candidates, so those cases are synthetic.
"""
import hashlib
from pathlib import Path

import pytest

from congress_api.models.html_metadata import MainContent
from congress_api.parsers import main_content
from congress_api.parsers.html_metadata import read_html_metadata
from congress_api.parsers.main_content import SHORT_MARKED_CHARS, block_text, select_main_content
from lxml import etree, html as dom

FIXTURES = Path(__file__).parent / 'fixtures/html_metadata'
LONG = 'Testimony sentence with enough words to count as a real statement. ' * 6


def select(body):
    if isinstance(body, str):
        body = body.encode()
    return select_main_content(body, read_html_metadata(body))


def page(inner, title='A hearing'):
    return f'<html><head><title>{title}</title></head><body><nav>Navigation words</nav>{inner}</body></html>'


def test_real_marked_testimony_excludes_page_chrome_and_is_cited():
    body = (FIXTURES / 'marked-testimony.html').read_bytes()
    content = select(body)
    assert content.outcome == 'marked' and content.property == 'content:encoded' and content.selector.startswith('/html/body')
    assert 'not testimony' not in content.text and len(content.text) >= SHORT_MARKED_CHARS
    assert content.candidates[0].rdfa_confirmed


def test_real_no_statement_page_is_not_replaced_by_other_page_text(monkeypatch):
    monkeypatch.setattr(main_content, '_fallback', lambda body: pytest.fail('short marked text must not fall back'))
    content = select((FIXTURES / 'marked-no-statement.html').read_bytes())
    assert content.outcome == 'marked_no_content' and content.text is None
    assert content.candidates[0].text == 'No prepared statement.'


def test_short_marked_text_keeps_its_links():
    content = select(page('<div property="content:encoded"><a href="/f.pdf">Click for the PDF</a></div>'))
    assert content.outcome == 'marked_no_content'
    assert [(link.href, link.text) for link in content.candidates[0].links] == [('/f.pdf', 'Click for the PDF')]


def test_itemprop_and_json_ld_are_candidates():
    assert select(page(f'<div itemprop="articleBody">{LONG}</div>')).property == 'itemprop:articleBody'
    json_ld = page(f'<script type="application/ld+json">{{"@type":"Article","articleBody":"{LONG}"}}</script>')
    content = select(json_ld)
    assert content.outcome == 'marked' and content.property == 'json-ld:articleBody'
    assert content.selector == '/formats/json-ld/items/0/articleBody'


def test_class_names_are_not_explicit_markup():
    content = select(page(f'<div class="entry-content">{LONG}</div>'))
    assert content.outcome in {'fallback_extractor', 'none'} and content.candidates == []


def test_nested_candidates_resolve_to_the_outermost():
    content = select(page(f'<div property="content:encoded"><p itemprop="articleBody">{LONG}</p><p>More.</p></div>'))
    assert content.outcome == 'marked' and len(content.candidates) == 1 and content.text.endswith('More.')


def test_identical_candidates_dedupe():
    content = select(page(f'<div property="content:encoded">{LONG}</div><div property="articleBody">{LONG}</div>'))
    assert content.outcome == 'marked' and len(content.candidates) == 2


def test_distinct_candidates_are_retained_and_fall_back(monkeypatch):
    monkeypatch.setattr(main_content, '_fallback', lambda body: ('extracted', None))
    content = select(page(f'<div property="content:encoded">{LONG}</div><div property="articleBody">Other. {LONG}</div>'))
    assert content.outcome == 'conflicting_candidates' and content.text == 'extracted' and len(content.candidates) == 2


def test_empty_candidate_and_no_candidate_fall_back(monkeypatch):
    monkeypatch.setattr(main_content, '_fallback', lambda body: ('extracted', None))
    assert select(page('<div property="content:encoded"> </div>')).fallback_reason == 'empty_candidate'
    assert select(page('<p>Words</p>')).outcome == 'fallback_extractor'
    monkeypatch.setattr(main_content, '_fallback', lambda body: (None, None))
    content = select(page('<p>Words</p>'))
    assert content.outcome == 'none' and content.text is None


def test_fallback_is_the_archive_reader_call(monkeypatch):
    import trafilatura
    calls = []
    monkeypatch.setattr(trafilatura, 'extract', lambda body, **kwargs: calls.append(kwargs) or 'text')
    select(page('<p>Words</p>'))
    assert calls == [dict(include_comments=False, output_format='txt')]


def test_non_substantive_pages_are_never_marked(monkeypatch):
    monkeypatch.setattr(main_content, '_fallback', lambda body: pytest.fail('nothing to extract'))
    assert select(page(f'<div property="content:encoded">{LONG}</div>', title='Page Not Found')).outcome == 'none'
    assert select(b'%PDF-1.7').outcome == 'none'


def test_walker_keeps_words_order_tails_and_drops_code():
    node = dom.fromstring('<div><p>t<b>he</b> <i>Health</i>e Vet</p><!-- c -->after<script>bad()</script>'
                          '<style>x</style><noscript>no</noscript><template>t</template><ul><li>one</li><li>two</li></ul>tail</div>')
    assert block_text(node) == 'the Healthe Vet\nafter\none\ntwo\ntail'


def test_walker_handles_nesting_past_the_recursion_limit():
    root = node = dom.Element('div')
    for _ in range(5000):  # built directly: the HTML parser stops at depth 256
        node = etree.SubElement(node, 'div')
    node.text = 'deep'
    assert block_text(root) == 'deep'


def test_ref_is_bounded_and_digests_the_full_text():
    content = select(page(f'<div property="content:encoded">{LONG * 5}</div>'))
    reference = content.ref('version')
    assert reference.text_sha256 == hashlib.sha256(content.text.encode()).hexdigest()
    assert reference.text_bytes == len(content.text.encode()) and reference.reader_version == 'version'
    assert len(reference.snippet) <= 280 and content.text.startswith(reference.snippet)
    assert content.text[len(reference.snippet)].isspace()


def test_ref_of_no_text_has_no_digest():
    reference = MainContent(outcome='none', body_sha256='0' * 64, text=None, selector=None, property=None,
                            candidates=[], fallback_reason=None).ref()
    assert reference.text_sha256 is None and reference.snippet is None and reference.text_bytes is None

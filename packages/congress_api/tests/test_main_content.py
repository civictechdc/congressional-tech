"""Explicit body markup selects text; short marked text never becomes extractor output.

Only the two marked-* fixtures come from real pages. The sample has no real page with
distinct competing candidates or nested candidates, so those cases are synthetic.
"""
import hashlib
from pathlib import Path

import pytest

from congress_api.models.html_metadata import MainContent
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


def test_real_no_statement_page_is_not_replaced_by_other_page_text():
    content = select((FIXTURES / 'marked-no-statement.html').read_bytes())
    assert content.outcome == 'marked_no_content' and content.text is None
    assert content.candidates[0].text == 'No prepared statement.'


def test_short_marked_text_keeps_its_links():
    content = select(page('<div property="content:encoded"><a href="/f.pdf">Click for the PDF</a></div>'))
    assert content.outcome == 'marked_no_content'
    assert [(link.href, link.text) for link in content.candidates[0].links] == [('/f.pdf', 'Click for the PDF')]


def test_json_ld_article_body_is_not_a_candidate():
    """Minimal reproduction of gov.uk f3a990b3513c8c42: JSON-LD articleBody carries raw markup."""
    markup = '<p>x</p><img src=x onerror=alert(1)>'
    content = select(page(f'<script type="application/ld+json">{{"@type":"Article","articleBody":"{markup}"}}</script><p>Words</p>'))
    assert (content.outcome, content.fallback_reason, content.text, content.candidates) == ('fallback_required', 'no_candidate', None, [])


def test_truncated_json_ld_does_not_replace_the_marked_body():
    json_ld = '<script type="application/ld+json">{"@type":"Article","articleBody":"Testimony sentence"}</script>'
    content = select(page(f'{json_ld}<div property="content:encoded">{LONG}</div>'))
    assert content.outcome == 'marked' and content.property == 'content:encoded'
    assert content.text == LONG.strip() and [c.property for c in content.candidates] == ['content:encoded']


def test_microdata_and_rdfa_article_body_are_not_candidates():
    content = select(page(f'<div itemprop="articleBody">{LONG}</div><div property="schema:articleBody">{LONG}</div>'))
    assert content.outcome == 'fallback_required' and content.candidates == []


def test_every_paragraph_is_kept_in_order():
    body = page(f'<div property="content:encoded"><p>Alpha one.</p><p>Bravo two.</p><p>Charlie three.</p><p>{LONG}</p></div>')
    assert select(body).text == 'Alpha one.\nBravo two.\nCharlie three.\n' + LONG.strip()


def test_real_marked_testimony_full_text_is_pinned():
    """The pinned words and their order were checked against an html5lib parse of the same
    content:encoded element when the pin was created: html5lib shares nothing with lxml but the bytes."""
    content = select((FIXTURES / 'marked-testimony.html').read_bytes())
    assert content.text == (FIXTURES / 'marked-testimony.txt').read_text()


def test_a_long_sidebar_does_not_win_over_a_short_body():
    sidebar = f'<aside property="content:encoded">{LONG}</aside>'
    content = select(page(f'{sidebar}<div property="content:encoded">Short statement body.</div>'))
    assert (content.outcome, content.fallback_reason, content.text) == ('fallback_required', 'multiple_candidates', None)
    assert len(content.candidates) == 2


def test_table_and_definition_cells_are_separate_tokens():
    table = '<table><caption>Claims</caption><tr><th>Year</th><th>Count</th></tr><tr><td>2006</td><td>6,658</td></tr></table>'
    words = block_text(dom.fromstring(f'<div>{table}<dl><dt>Term</dt><dd>Meaning</dd></dl>a<hr>b<pre>code</pre>'
                                      '<figure>img<figcaption>Cap</figcaption></figure></div>')).split()
    assert words == ['Claims', 'Year', 'Count', '2006', '6,658', 'Term', 'Meaning', 'a', 'b', 'code', 'img', 'Cap']


def test_soft_hyphens_do_not_split_words():
    assert block_text(dom.fromstring('<p>capaci\u00adties and nec\u00adessarily</p>')) == 'capacities and necessarily'


def test_hidden_text_is_excluded_and_its_tail_kept():
    node = dom.fromstring('<div><p>A <span hidden>X</span> B</p><p style="display: none">Y</p>'
                          '<p style="color:red;VISIBILITY:hidden">Z</p><p style="display:block">C</p></div>')
    assert block_text(node) == 'A B\nC'


def test_hidden_rule_matches_the_archive_reading():
    """Both readers recognize ordinary display and visibility declarations."""
    import inspect
    import re
    from congress_api.parsers import archive_readings, main_content
    source = inspect.getsource(archive_readings._markup_facts)
    assert "'hidden' in node.attrib" in source
    for style in ('display:none', 'DISPLAY : none', 'visibility:hidden', 'display:block', 'visibility: visible', ''):
        assert bool(main_content.HIDDEN_STYLE.search(style)) == bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', style, re.I))


def test_class_names_are_not_explicit_markup():
    content = select(page(f'<div class="entry-content">{LONG}</div>'))
    assert content.outcome == 'fallback_required' and content.candidates == []


def test_nested_candidates_resolve_to_the_outermost():
    content = select(page(f'<div property="content:encoded"><p property="content:encoded">{LONG}</p><p>More.</p></div>'))
    assert content.outcome == 'marked' and len(content.candidates) == 1 and content.text.endswith('More.')


def test_identical_candidates_dedupe():
    content = select(page(f'<div property="content:encoded">{LONG}</div><div property="content:encoded">{LONG}</div>'))
    assert content.outcome == 'marked' and len(content.candidates) == 2


def test_distinct_candidates_are_retained_and_require_the_stored_reading():
    content = select(page(f'<div property="content:encoded">{LONG}</div><div property="content:encoded">Other. {LONG}</div>'))
    assert content.outcome == 'fallback_required' and content.fallback_reason == 'multiple_candidates'
    assert content.text is None and len(content.candidates) == 2


def test_empty_and_missing_candidates_require_the_stored_reading():
    assert select(page('<div property="content:encoded"> </div>')).fallback_reason == 'empty_candidate'
    assert select(page('<p>Words</p>')).fallback_reason == 'no_candidate'


def test_no_extractor_runs_here(monkeypatch):
    import trafilatura
    monkeypatch.setattr(trafilatura, 'extract', lambda *a, **k: pytest.fail('reuse the stored reading'))
    assert select(page('<p>Words</p>')).outcome == 'fallback_required'


def test_non_substantive_pages_are_never_marked():
    assert select(page(f'<div property="content:encoded">{LONG}</div>', title='Page Not Found')).outcome == 'none'
    assert select(b'%PDF-1.7').outcome == 'none'


def test_a_candidate_past_the_parser_depth_is_failed_not_none():
    deep = '<div>' * 300 + f'<p property="content:encoded">{LONG}</p>' + '</div>' * 300
    content = select(page(deep))
    assert content.outcome == 'failed' and content.fallback_reason == 'document_too_deep'


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



def test_hidden_and_rebound_markers_cannot_supply_testimony():
    text = select(page(f'<div hidden><div property="content:encoded">{LONG}</div></div>'
                       f'<div prefix="content: https://example.test/fake/" property="content:encoded">{LONG}</div>'))
    assert text.outcome == 'fallback_required' and text.candidates == []
    visible = select(page(f'<div property="content:encoded"><p style="--display:none">{LONG}</p></div>'))
    assert visible.text == LONG.strip()


def test_same_text_with_conflicting_links_requires_fallback():
    text = select(page(f'<div property="content:encoded">{LONG}<a href="/a">Exhibit</a></div>'
                       f'<div property="content:encoded">{LONG}<a href="/b">Exhibit</a></div>'))
    assert text.outcome == 'fallback_required' and text.fallback_reason == 'multiple_candidates'


def test_empty_then_short_marker_has_consistent_text_reference():
    from congress_api.parsers.html_metadata import reading_row
    body = page('<div property="content:encoded"></div><div property="content:encoded">A brief statement.</div>').encode()
    row = reading_row(body)
    fields = {item['field']: item['value'] for item in row['fields']}
    assert fields['main_content:selector'] == '/html/body/div[2]'
    assert row['text_head'] == fields['main_content:text'] == 'A brief statement.'
    assert row['text_bytes'] == len(b'A brief statement.')
    assert fields['main_content:sha256'] == hashlib.sha256(b'A brief statement.').hexdigest()

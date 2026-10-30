"""Transcript types follow explicit publisher sections, not nearby topic words."""
from pathlib import Path

import pytest

from congress_api.parsers.senate import parsed
from congress_api.parsers.senate_page import documents

PAGE = 'https://www.foreign.senate.gov/hearings/modernizing-us-alliances-and-partnerships-in-the-indo-pacific'
LINK = 'https://www.foreign.senate.gov/download/04-17-24__2024-modernizing-us-alliances'
RAW = (Path(__file__).parent / 'fixtures/meeting_inventory/senate-foreign-transcripts.html').read_text()


def test_real_nested_transcript_heading_classifies_the_link_and_survives_source_index():
    page = parsed(RAW, PAGE)
    assert page['documents'] == [('transcript', '04 17 24 -- 2024 Modernizing U.S. Alliances.pdf', LINK)]
    occurrence, = page['document_metadata'][LINK]['occurrences']
    assert occurrence['headings'] == ['Transcripts']
    assert documents(RAW, PAGE) == page['documents']


@pytest.mark.parametrize('heading', ['Transcripts', 'Transcript', 'Hearing Transcripts', 'Related Transcripts'])
def test_direct_headings_and_single_quoted_links(heading):
    page = parsed(f"<section><h2>{heading}</h2><ul><li><a href='/download/opaque'>Download</a></li></ul></section>", PAGE)
    assert page['documents'][0][0] == 'transcript'


@pytest.mark.parametrize('raw', [
    '<section><h2>Related Files</h2><a href="/download/opaque">US Response to the Coup in Burma.pdf</a></section>',
    '<section><h2>Transcript requests</h2><a href="/download/opaque">Form</a></section>',
    '<h1>Transcripts</h1><section><a href="/download/opaque">An unheaded separate section</a></section>',
    '<section><h2>Transcripts</h2><section><a href="/download/opaque">Nested unheaded section</a></section></section>',
    '<section><h2>Transcripts</h2></section><section><a href="/download/opaque">Other</a></section>',
    '<nav><h2>Transcripts</h2></nav><main><a href="/download/opaque">Other</a></main>',
    '<div class="Hearing__section"><div class="Hearing__sectionHeading"><h2>Transcripts</h2></div></div><div class="Hearing__section"><a href="/download/opaque">Other</a></div>',
])
def test_section_words_do_not_leak_into_unrelated_links(raw):
    assert parsed(raw, PAGE)['documents'][0][0] == 'other'

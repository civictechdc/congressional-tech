"""Tests for Congressional CMS time-travel nav stripping, <pre> preservation, and bare-UUID HTML."""
from lxml import html as dom

from congress_api.parsers.congress import (
    clean_congressional_html,
    is_bare_uuid_html,
    sniff_html_markup,
)
from congress_api.parsers.main_content import (
    block_text,
    strip_congressional_cms_chrome,
)


def test_cms_nav_time_travel_119th_chrome_stripped_on_archived_hearing_page():
    archived_2018_html = """<!DOCTYPE html>
    <html lang="en">
    <head>
      <title>Full Committee Hearing on Rural Broadband | House Agriculture</title>
      <script>window.__LIVE_CONGRESS__ = 119;</script>
      <style>.nav { display: block; }</style>
    </head>
    <body>
      <header class="site-header" role="banner">
        <div>119th Congress | Majority: Rep. Glenn "GT" Thompson | Minority: Rep. Angie Craig</div>
        <nav id="site-navigation" role="navigation">
          <ul><li>Home</li><li>About</li><li>Subcommittees</li><li>Hearings</li></ul>
        </nav>
      </header>
      <div class="breadcrumb">Home &gt; Hearings &gt; 115th Congress</div>
      <aside class="region-sidebar-first">
        <p>119th Congress Official Website Navigation</p>
      </aside>
      <main id="main-content" class="node-content">
        <h1>Examining Rural Broadband Deployment in the 2018 Farm Bill</h1>
        <p>Date: Thursday, July 19, 2018 — 10:00 AM</p>
        <p>The Committee on Agriculture met in 1300 Longworth House Office Building to receive testimony from rural telecommunications providers regarding broadband deployment across underserved agricultural communities.</p>
      </main>
      <footer class="site-footer">
        <p>Privacy Policy | Accessibility | 119th Congress Official Website</p>
      </footer>
    </body>
    </html>"""

    for cleaned in (
        strip_congressional_cms_chrome(archived_2018_html),
        clean_congressional_html(archived_2018_html),
    ):
        assert '119th Congress' not in cleaned
        assert 'Glenn "GT" Thompson' not in cleaned
        assert '__LIVE_CONGRESS__' not in cleaned
        assert 'Examining Rural Broadband Deployment in the 2018 Farm Bill' in cleaned
        assert 'July 19, 2018' in cleaned
        assert '1300 Longworth House Office Building' in cleaned


def test_pre_hearing_transcript_preserved_while_script_style_noscript_template_dropped():
    gpo_pre_html = """<!DOCTYPE html>
    <html>
    <head><title>- OVERSIGHT OF FEDERAL INFRASTRUCTURE</title><style>body{font:monospace}</style></head>
    <body>
      <nav class="navbar">Skip to main content Toggle navigation 119th Congress</nav>
      <script>console.log("analytics");</script>
      <noscript>Enable JS</noscript>
      <template><p>Hidden template text</p></template>
      <pre>
[House Hearing, 114 Congress]
[From the U.S. Government Publishing Office]

                  OVERSIGHT OF FEDERAL INFRASTRUCTURE
=======================================================================

    The Chairman. The subcommittee will come to order.
    Without objection, the chair is authorized to declare a recess.

    PANEL I:
        Hon. Anthony Foxx, Secretary, U.S. Department of Transportation ..   7
      </pre>
    </body>
    </html>"""

    for cleaned in (
        strip_congressional_cms_chrome(gpo_pre_html),
        clean_congressional_html(gpo_pre_html),
    ):
        assert 'analytics' not in cleaned
        assert 'Enable JS' not in cleaned
        assert 'Hidden template text' not in cleaned
        assert 'Toggle navigation' not in cleaned
        assert '[House Hearing, 114 Congress]' in cleaned
        assert '    The Chairman. The subcommittee will come to order.' in cleaned
        assert '        Hon. Anthony Foxx, Secretary, U.S. Department of Transportation ..   7' in cleaned

    node = dom.fromstring('<div><p>Intro</p><pre>  Line 1\n\n    Indented Line 2</pre><script>x()</script></div>')
    assert block_text(node) == 'Intro\n  Line 1\n\n    Indented Line 2'


def test_bare_uuid_html_content_sniffing():
    html_doc = b'  \xef\xbb\xbf<!-- cached -->\n<!DOCTYPE html>\n<html><body><h1>Hearing</h1></body></html>'
    html_tag_only = '<html><head><title>Notice</title></head><body><p>Body</p></body></html>'
    pdf_doc = b'%PDF-1.7\n1 0 obj\n%%EOF'

    assert sniff_html_markup(html_doc) is True
    assert sniff_html_markup(html_tag_only) is True
    assert sniff_html_markup(pdf_doc) is False

    # Bare UUIDs and extensionless Senate/House download endpoints return True
    assert is_bare_uuid_html(
        html_doc,
        'https://www.finance.senate.gov/imo/media/doc/525f6a3b-1234-4abc-9def-0123456789ab',
    ) is True
    assert is_bare_uuid_html(
        html_tag_only,
        'https://www.foreign.senate.gov/hearings/2021/05/nomination-hearing/794840bc-48b3-4027-814a-eb756fb02975',
    ) is True
    assert is_bare_uuid_html(html_doc, '525f6a3b-1234-4abc-9def-0123456789ab') is True

    # Explicit .html / .htm URLs are not bare-UUID / extensionless HTML
    assert is_bare_uuid_html(
        html_doc,
        'https://www.govinfo.gov/content/pkg/CHRG-118hhrg55555/html/CHRG-118hhrg55555.htm',
    ) is False
    assert is_bare_uuid_html(
        html_doc,
        'https://www.senate.gov/hearings/index.html',
    ) is False

    # Actual PDF bytes at a bare-UUID URL are never HTML
    assert is_bare_uuid_html(
        pdf_doc,
        'https://www.finance.senate.gov/imo/media/doc/525f6a3b-1234-4abc-9def-0123456789ab',
    ) is False

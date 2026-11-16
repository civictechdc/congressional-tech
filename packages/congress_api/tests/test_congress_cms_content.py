"""Tests for opt-in committee/member CMS HTML content selection (`congress_cms_content`)."""
from __future__ import annotations

import json

from congress_api.parsers import body_text
from congress_api.parsers.congress_cms_content import POLICY, select_congress_cms_content


def test_cms_prunes_nav_header_sidebar_share_and_preserves_pre_transcript_and_tails():
    html = b"""<!DOCTYPE html>
    <html>
      <body>
        <header class="site-header"><nav><a href="/">Skip to main content</a> Home About</nav></header>
        <main id="main-content">
          <h1>Subcommittee Hearing on Grid Reliability</h1>
          <div class="social-share"><a href="#">Share on Facebook</a></div>
          <p>Opening remarks by <span class="nav-inline-safe">the</span> Chairman follow below.</p>
          <pre>
          [114th Congress, 2nd Session]
          Mr. CHAIRMAN. The subcommittee will come to order.
          Ms. WITNESS. Thank you for the invitation to testify today.
          </pre>
        </main>
        <aside class="region-sidebar-second">Related Press Releases</aside>
        <footer id="site-footer">Privacy Policy | Accessibility</footer>
      </body>
    </html>"""

    ordinary = body_text.markup_text(html, "html_text")
    selected = body_text.markup_text(html, "html_text", select_publisher_content=POLICY)

    assert "Skip to main content" in ordinary.text
    assert "Privacy Policy" in ordinary.text

    assert selected.status == "completed"
    assert "Skip to main content" not in selected.text
    assert "Share on Facebook" not in selected.text
    assert "Related Press Releases" not in selected.text
    assert "Privacy Policy" not in selected.text
    assert "Subcommittee Hearing on Grid Reliability" in selected.text
    assert "Opening remarks by the Chairman follow below." in selected.text
    assert "Mr. CHAIRMAN. The subcommittee will come to order." in selected.text
    assert "Ms. WITNESS. Thank you for the invitation to testify today." in selected.text

    ev = json.loads(selected.fields["content_selection"])
    assert ev["policy"] == POLICY
    assert ev["outcome"] == "selected"
    assert ev["scope"] == "main_landmark"


def test_cms_strips_retroactive_119th_congress_banner_on_earlier_congress_archive_pages():
    archived_115th = (
        "<!DOCTYPE html><html><body><main>"
        "<div>119th Congress</div>"
        "<h1>March 14, 2018 Markup of H.R. 5100 (115th Congress)</h1>"
        "<p>" + ("The Committee ordered H.R. 5100 reported favorably to the House. " * 6) + "</p>"
        "</main></body></html>"
    ).encode("utf-8")

    res = body_text.markup_text(archived_115th, "html_text", select_publisher_content=POLICY)
    assert res.status == "completed"
    assert "119th Congress" not in res.text
    assert "115th Congress" in res.text
    ev = json.loads(res.fields["content_selection"])
    assert ev["time_travel_banner_stripped"] is True

    genuine_119th = (
        "<!DOCTYPE html><html><body><main>"
        "<div>119th Congress</div>"
        "<h1>February 12, 2025 Full Committee Hearing</h1>"
        "<p>" + ("Testimony on 2025 oversight priorities before the 119th Congress. " * 6) + "</p>"
        "</main></body></html>"
    ).encode("utf-8")
    res_119 = body_text.markup_text(genuine_119th, "html_text", select_publisher_content=POLICY)
    assert "119th Congress" in res_119.text


def test_cms_skips_error_responses_and_congress_gov_legislative_wrappers():
    from pathlib import Path

    fixture = (Path(__file__).parent / "fixtures/response_roles/house-meeting-not-found.html").read_bytes()
    err_html = fixture.replace(b"<body>", b"<body><nav>Home</nav>", 1)
    sel = select_congress_cms_content(err_html)
    assert sel is not None and sel.body is None and sel.evidence["outcome"] == "fallback"
    assert sel.evidence["reason"] == "response_role_error_response"

    cgov_html = b"""<html><head><link rel="canonical" href="https://www.congress.gov/bill/118th-congress/house-bill/1/text"></head>
    <body><div class="billTextContainer"><pre>H. R. 1 Be it enacted...</pre></div></body></html>"""
    sel_cgov = select_congress_cms_content(cgov_html)
    assert sel_cgov is None


def test_inline_tail_preserved_when_pruning_embedded_share_node():
    html = (
        "<html><body><main>"
        "<h1>Committee Statement on Infrastructure Permitting Reform</h1>"
        "<p>Chairman Smith stated, <div class='share-links'>Tweet</div> that permitting reform is urgent across all fifty states "
        "and territories to lower energy costs for families and manufacturers.</p>"
        "</main></body></html>"
    ).encode("utf-8")
    res = body_text.markup_text(html, "html_text", select_publisher_content=POLICY)
    assert "Tweet" not in res.text
    assert "that permitting reform is urgent across all fifty states" in res.text

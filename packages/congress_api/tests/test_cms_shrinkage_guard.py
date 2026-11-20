"""Tests for the empirical Congressional CMS HTML shrinkage guard (ct-m704).

Plants both observed content-loss mechanisms:
1. Substantive body placed in sibling sections outside ``role="main"`` (e.g. 9d3094e1, 653afe17).
2. Substantive body placed inside ``role="main"`` within a ``display:none`` container (e.g. 9b166e1e).
"""
from __future__ import annotations

import json

from congress_api.parsers.body_text import markup_text
from congress_api.parsers.congress_cms_content import POLICY, select_congress_cms_content
from congress_api.parsers.main_content import (
    CMS_GUARD_MAX_CHOSEN_BYTES,
    CMS_GUARD_MIN_DEFAULT_BYTES,
    clean_congressional_html,
    cms_cleaned_text_too_small,
)


def test_cms_shrinkage_guard_reverts_planted_sibling_outside_role_main():
    """Mechanism 1: short title inside role=main while substantive letter lives in sibling sections."""
    signers = ' '.join(
        f'{i}. Representative Signer {i} concerning Inter-American human rights obligations.'
        for i in range(1, 45)
    )
    html = (
        '<!DOCTYPE html><html><head><title>Open Letter</title></head><body>'
        '<nav class="site-nav">Committee Navigation Links About Hearings Press</nav>'
        '<div role="main"><h1>Open Letter on Human Rights Protections in Nicaragua</h1></div>'
        f'<section class="article-body"><p>Dear Secretary of State: We write to urge immediate diplomatic engagement. {signers}</p></section>'
        '<footer class="site-footer">2170 Rayburn House Office Building</footer>'
        '</body></html>'
    ).encode('utf-8')

    selection = select_congress_cms_content(html)
    assert selection is not None
    assert selection.body is None
    assert selection.evidence['outcome'] == 'fallback'
    assert selection.evidence['reason'] == 'excessive_shrinkage_guard'
    assert selection.evidence['scope'] == 'main_landmark'
    assert selection.evidence['chosen_bytes'] < CMS_GUARD_MAX_CHOSEN_BYTES
    assert selection.evidence['default_bytes'] >= CMS_GUARD_MIN_DEFAULT_BYTES

    cleaned_reading = markup_text(html, 'html_text', select_publisher_content=POLICY)
    default_reading = markup_text(html, 'html_text', select_publisher_content=False)
    assert cleaned_reading.status == 'completed'
    assert cleaned_reading.text == default_reading.text
    assert 'Representative Signer 44' in cleaned_reading.text
    evidence = json.loads(dict(pair.values() for pair in cleaned_reading.row()['fields'])['content_selection'])
    assert evidence['outcome'] == 'fallback'
    assert evidence['reason'] == 'excessive_shrinkage_guard'

    assert 'Representative Signer 44' in clean_congressional_html(html)


def test_cms_shrinkage_guard_reverts_planted_hidden_container_inside_role_main():
    """Mechanism 2: short notice heading visible in role=main while witness panel sits in display:none."""
    witnesses = ' '.join(
        f'Panelist {i}: Hon. Witness {i}, Deputy Assistant Secretary for Financial Stability Oversight.'
        for i in range(1, 40)
    )
    html = (
        '<!DOCTYPE html><html><head><title>Banking Hearing Notice</title></head><body>'
        '<header class="site-header">United States Senate Committee on Banking, Housing, and Urban Affairs</header>'
        '<main role="main">'
        '<h1>Full Committee Hearing: Semiannual Monetary Policy Report to the Congress</h1>'
        f'<div class="hearing-witness-tab" style="display:none"><p>Witness List and Panel Schedule: {witnesses}</p></div>'
        '</main>'
        '<footer class="site-footer">534 Dirksen Senate Office Building</footer>'
        '</body></html>'
    ).encode('utf-8')

    selection = select_congress_cms_content(html)
    assert selection is not None
    assert selection.body is None
    assert selection.evidence['outcome'] == 'fallback'
    assert selection.evidence['reason'] == 'excessive_shrinkage_guard'
    assert selection.evidence['scope'] == 'main_landmark'
    assert selection.evidence['chosen_bytes'] < CMS_GUARD_MAX_CHOSEN_BYTES
    assert selection.evidence['default_bytes'] >= CMS_GUARD_MIN_DEFAULT_BYTES

    cleaned_reading = markup_text(html, 'html_text', select_publisher_content=POLICY)
    default_reading = markup_text(html, 'html_text', select_publisher_content=False)
    assert cleaned_reading.status == 'completed'
    assert cleaned_reading.text == default_reading.text
    assert 'Hon. Witness 39' in cleaned_reading.text

    assert 'Hon. Witness 39' in clean_congressional_html(html)


def test_cms_shrinkage_guard_preserves_legitimate_chrome_heavy_pages_outside_thresholds():
    """Boundary checks: guard only fires when chosen <500 B, default >=2,000 B, and chosen <10% of default."""
    assert cms_cleaned_text_too_small(202, 68640) is True
    assert cms_cleaned_text_too_small(188, 2265) is True
    assert cms_cleaned_text_too_small(266, 4057) is True

    # >=500 B chosen prose (e.g. short bill summary surrounded by 8 KB Congress.gov chrome) stays selected
    assert cms_cleaned_text_too_small(500, 8000) is False
    # >=10% of default stays selected
    assert cms_cleaned_text_too_small(250, 2500) is False
    # <2,000 B default stays selected
    assert cms_cleaned_text_too_small(180, 1999) is False

    nav_links = ' '.join(f'<a href="/item/{i}">Committee Navigation Link {i}</a>' for i in range(1, 120))
    substantive_prose = (
        'Chairman Smith convened the Subcommittee on Oversight to examine federal procurement modernization, '
        'agency audit readiness, inspector general recommendations, statutory reporting timelines, '
        'chief information officer authorities, cloud security baselines, and taxpayer cost savings '
        'across civilian and defense acquisition programs during the 118th Congress. ' * 2
    )
    html = (
        f'<!DOCTYPE html><html><body><nav class="site-nav">{nav_links}</nav>'
        f'<main><p>{substantive_prose}</p></main>'
        '<footer class="site-footer">Subcommittee Footer</footer></body></html>'
    ).encode('utf-8')

    selection = select_congress_cms_content(html)
    assert selection is not None and selection.body is not None
    assert selection.evidence['outcome'] == 'selected'
    reading = markup_text(html, 'html_text', select_publisher_content=POLICY)
    assert 'Committee Navigation Link 1' not in reading.text
    assert 'federal procurement modernization' in reading.text

"""Pure parsing for Senate/joint sites: seven witness layouts and linked files.

Witness headings exclude senators' statements. JEC running text is not interpreted. Listings
locate pages; only a page's own date and subject establish which meeting it is.
"""

import datetime as dt
import html
import re
from collections import Counter
from urllib.parse import parse_qs, urljoin, urlsplit

from lxml import html as dom

from congress_api.parsers.text import text
from congress_api.parsers.witness_names import is_name, witness
from congress_api.parsers.document_links import feed_link, http_url, is_document_url

## where each committee keeps its hearing pages
SITE = {"ssaf00": "agriculture.senate.gov", "ssap00": "appropriations.senate.gov", "ssas00": "armed-services.senate.gov", "ssbk00": "banking.senate.gov",
        "ssbu00": "budget.senate.gov", "sscm00": "commerce.senate.gov", "sseg00": "energy.senate.gov", "ssev00": "epw.senate.gov", "ssfi00": "finance.senate.gov",
        "ssfr00": "foreign.senate.gov", "ssga00": "hsgac.senate.gov", "sshr00": "help.senate.gov", "ssju00": "judiciary.senate.gov", "ssra00": "rules.senate.gov",
        "sssb00": "sbc.senate.gov", "ssva00": "veterans.senate.gov", "slia00": "indian.senate.gov", "spag00": "aging.senate.gov", "slin00": "intelligence.senate.gov",
        "jsec00": "jec.senate.gov", "jcse00": "csce.gov", "scnc00": "drugcaucus.senate.gov"}


## the forms a listing's address takes
LISTINGS = ["/hearings?PageNum_rs={}", "/committee-activity/hearings?PageNum_rs={}", "/hearings/?mt_page={}", "/committee-activity/hearings/?mt_page={}",
            "/hearings?page={}", "/public/index.cfm/hearings?page={}", "/public/index.cfm/hearings-calendar?page={}", "/hearings-and-markups?PageNum_rs={}",
            "/hearings-briefings/hearings?page={}"]


## a hearing's page: /hearings/<name>, /meetings/<name>, hearings?ID=<id>, /2024/5/<name>
HEARING_LINK = re.compile(r"<a[^>]+href=\"((?:https?://[\w.\-]+)?/(?:[\w\-/.]*/)?(?:(?:hearings?|meetings|hearings-and-markups)/[^\"#?]+|hearings(?:-calendar)?\?(?:ID|id)=[\w\-]+"
                          r"|\d{4}/\d{1,2}/[^\"#?/]+))\"[^>]*>(.*?)</a>", re.S)


FIRST_RECORD = dt.date(2019, 6, 1)  # Congress.gov's Senate meeting records begin in June 2019


OWN = 5  # a line on more of a site's pages than this is the site's, not a hearing's


NEAR = 365  # days between a page's place in the listing and its hearing, at most


## a page that is a business meeting's, by its name in the address and its title in the listing
BUSINESS = re.compile(r"business[ \-_]meeting|executive[ \-_](?:business[ \-_])?session|mark[ \-_]?up", re.I)


MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


## "6/12/2019", "06.12.19", "June 12, 2019", "Wednesday, March 11th, 2026", "Jun 24, 2026", "2019-06-12"
DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b|\b((?:" + "|".join(MONTHS) + r")[a-z]*)\.? (\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b", re.I)


# Keep match positions for the legacy preceding-heading label; the shared
# predicate owns which URLs are documents, including extensionless CMS routes.
ANCHOR = re.compile(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.S | re.I)


def file_anchors(page_html, url):
    for link in ANCHOR.finditer(page_html):
        value = html.unescape(link.group(1)).strip()
        if is_document_url(value, publisher_routes=True):
            yield link, urljoin(url, value)


KINDS = [("transcript", r"transcript"), ("questions for the record", r"qfr|questions?[ \-_]for[ \-_]the[ \-_]record|responses?[ \-_]to[ \-_](?:written[ \-_])?questions"),
         ("questionnaire", r"questionnaire"), ("witness biography", r"\bbio(?:graphy)?\b|/bio_"), ("witness statement", r"testimony"), ("member statement", r"state?ment")]

AMENDMENT_LIST = re.compile(r".+\bas (?:amended|modified) by(?::(?:\s*PASSED BY VOICE VOTE)?)?", re.I)


def person(name, details, page):
    """One witness row from a name as the page writes it ("The Honorable Jay Bhattacharya, M.D., Ph.D.") and the lines under it."""
    details = [d for d in (text(d) for d in details) if d and not re.match(r"(download|view|watch) ", d, re.I)]
    return {"name": witness(text(name))["name"], "position": details[0] if details else "", "organization": ", ".join(details[1:3]), "page": page}


def sections(page_html, levels):
    """The page cut at its headings, less the sections headed as statements or remarks: the senators', laid out like witnesses."""
    return [s for s in re.split(rf"(?=<h[{levels}]\b)", page_html) if not (s.startswith("<h") and re.search(r"statement|remarks", text(s.split("</h")[0]), re.I))]


def witnesses(page_html, url, *, plain=False):
    """The witnesses a hearing page lists, by whichever of the seven layouts it uses."""
    page_html, out = re.sub(r"<!--.*?-->", "", page_html, flags=re.S), []
    if "capigacr-widget-card" in page_html:
        for section in re.split(r"capigacr-widget-card__panel-section\"", page_html)[1:]:
            heading = re.search(r"panel-section-title[^>]*>(.*?)</h2>", section, re.S)
            if heading and re.search(r"statement", text(heading.group(1)), re.I):
                continue  # senators' statements are laid out like witnesses
            for card in re.split(r"<li class=\"capigacr-widget-card\"", section)[1:]:
                name = re.search(r"capigacr-widget-card__title[^>]*>(.*?)</h3>", card, re.S)
                if name:
                    out.append(person(name.group(1), re.findall(r"member-detail-item[^>]*>(.*?)</div>", card, re.S), url))
    elif "witness-content" in page_html:
        for item in ("<li" + i for s in sections(page_html, "2") for i in re.split(r"<li\b", s)[1:]):
            details = re.search(r"<div class=\"witness-content[^\"]*\">(.*?)</div>\s*</div>", item, re.S)
            if details:
                ## the name is the item's heading, and what stands between it and the details is the post; with no
                ##  heading, the name is the last line above the details: "1. XIAO Qiang", "Robert L. Listenbee, Jr."
                above = [l for l in (text(l) for l in re.split(r"</(?:p|div|h\d)>", item[:details.start()])) if l]
                heading = list(re.finditer(r"<h\d[^>]*>(.*?)</h\d>", item[:details.start()], re.S))
                post = [l for l in (text(l) for l in re.split(r"</(?:p|div)>", item[heading[-1].end():details.start()])) if l] if heading else []
                if above:
                    out.append(person(re.sub(r"^\d+\.\s*", "", text(heading[-1].group(1)) if heading else above[-1]),
                                      post + re.findall(r"<div>(.*?)</div>", details.group(1), re.S), url))
    elif "class=\"vcard" in page_html:
        start = re.search(r">\s*(Witnesses|Nominees|Panel)", page_html)
        for card in re.split(r"<li[^>]*class=\"vcard", page_html[start.start() if start else 0:])[1:]:
            card = card.split("</li>")[0] if "class=\"party\"" not in card.split("<ul")[0] else ""
            name = re.search(r"class=\"fn\">((?:\s*<span[^>]*>[^<]*</span>)*[^<]*)</span>", card, re.S)  # "<span>Dr.</span> Saule T. Omarova"
            if name:
                prefix = re.search(r"class=\"honorific-prefix\">(.*?)</span>", card, re.S)
                out.append(person(f"{text(prefix.group(1)) if prefix else ''} {text(name.group(1))}", re.findall(r"class=\"(?:title|org)\">(.*?)</div>", card, re.S), url))
    elif re.search(r"class=\"(?:full-name|person)\"", page_html):
        for item in (i for s in sections(page_html, "23") for i in re.split(r"<li class=\"[^\"]*list-group-item", s)[1:]):
            name = re.search(r"class=\"(?:full-name|person)\">(.*?)</(?:h4|div)>", item, re.S)
            if name:
                out.append(person(name.group(1), re.findall(r"class=\"(?:occupation|organization)\">(.*?)</div>", item, re.S), url))
    elif "paragraph--witness" in page_html:
        for item in re.split(r"paragraph--witness\"", page_html)[1:]:
            name = re.search(r"witness__field-name\">(.*?)</div>", item, re.S)
            if name:
                out.append(person(name.group(1), re.findall(r"witness__field-(?:position|organization)\">(.*?)</div>", item, re.S), url))
    elif "field-hearing-new-witness" in page_html:
        for item in re.split(r"field-collection-item-field-hearing-new-witness", page_html)[1:]:
            name = re.search(r"class=\"group-header\">(.*?)</div>", item, re.S)
            if name:
                out.append(person(name.group(1), re.findall(r"<(?:em|span)>(.*?)</(?:em|span)>", item.split("more-link")[0], re.S), url))
    else:
        start = re.search(r">\s*Witnesses\s*</h\d>", page_html)
        for item in re.split(r"jet-listing-grid__item ", page_html[start.start():] if start else "")[1:]:
            names = re.findall(r"<h[34] class=\"jet-listing-dynamic-field__content\">(.*?)</h[34]>", item, re.S)
            if names:
                out.append(person(" ".join(names), re.findall(r"<(?:div|p) class=\"jet-listing-dynamic-field__content\">(.*?)</(?:div|p)>", item, re.S), url))
    if plain:
        root = dom.fromstring(page_html)
        out += [{**witness(line), 'page': url} for _, line in plain_witness_links(root)]
    seen = set()
    return [w for w in out if is_name(w["name"]) and not (w["name"] in seen or seen.add(w["name"]))]


def section_document_kind(metadata):
    """Read an exact publisher section label, never a substring of a topic.

    A URL appearing under different sections keeps separate occurrence claims;
    its aggregate type is supplied only when every occurrence agrees.
    """
    occurrences = (metadata or {}).get("occurrences") or [metadata or {}]
    kinds = []
    for occurrence in occurrences:
        headings = occurrence.get("headings") or []
        heading = headings[0].strip().rstrip(":").strip() if len(headings) == 1 else ""
        kind = None
        if re.fullmatch(r"(?:hearing |related |markup )?transcripts?", heading, re.I):
            kind = "transcript"
        elif re.fullmatch(r"legislative reports?", heading, re.I):
            kind = "committee report"
        elif re.fullmatch(r"(?:(?:witness|written|prepared) )?testimony(?: on the following bills| submitted for the record)?", heading, re.I):
            kind = "witness statement"
        elif re.fullmatch(r"(?:member|opening) statements?", heading, re.I):
            kind = "member statement"
        elif re.fullmatch(r"legislation", heading, re.I):
            kind = "legislative text"
        elif re.fullmatch(r"(?:stakeholder )?responses to senators['’]? questions", heading, re.I):
            kind = "questions for the record"
        elif (re.fullmatch(r"(?:view (?:the manager['’]s|all agreed to member) )?amendments", heading, re.I)
              or AMENDMENT_LIST.fullmatch(heading)):
            kind = "committee amendment"
        kinds.append(kind)
    return kinds[0] if kinds[0] and all(kind == kinds[0] for kind in kinds) else None


TRANSCRIPT_LABEL = re.compile(r'(?:(?:official|hearing|markup) )?transcript|printed hearing text', re.I)


def literal_document_kind(label, url):
    """The existing link-word inference, independent of page structure."""
    if TRANSCRIPT_LABEL.fullmatch(label.strip()):
        return 'transcript'
    return next((kind for kind, pattern in KINDS
        if re.search(pattern, f"{label} {url.rsplit('/', 1)[-1]}", re.I)), "other")


def _document_occurrence_context(occurrence):
    """Interpret one link using only its own heading, label, field, and card."""
    related = occurrence.get('related_page') or {}
    kind = related.get('document_kind') or section_document_kind(occurrence)
    basis = related['basis'] if related.get('document_kind') else "publisher_section_heading" if kind else None
    labels = occurrence.get("labels") or []
    card = occurrence.get("witness_card") or {}
    attributes = occurrence.get("attributes") or []
    if not kind and re.match(r"^Read\b.{0,100}\bopening statement\b", occurrence.get('line_text') or occurrence.get('paragraph_text', ''), re.I):
        kind, basis = 'member statement', 'publisher_paragraph_label'
    if not kind and card.get('layout') == 'plain-witness-line':
        literal = literal_document_kind(' '.join(labels), ' '.join(a.get('href', '') for a in attributes))
        if literal in {'other', 'member statement', 'witness statement'}:
            kind, basis = 'witness statement', 'publisher_witness_line'
    if not kind and any(re.fullmatch(r"(?:Witness |Panelist |Speaker )?Biograph(?:y|ies)",
                                    label.strip(), re.I) for label in labels):
        kind, basis = "witness biography", "publisher_link_label"
    # CSCE uses the same generic transcript icon for whole-event transcripts
    # and witness files. The enclosing testimony field supplies the role.
    if not kind and card.get("layout") == "paragraph--witness" and any(
            "witness__field-testimony" in (container.get("class") or "").split()
            for container in occurrence.get("container_attributes") or []):
        kind, basis = "witness statement", "publisher_witness_field"
    # The broad section can contain a bill and amendments to it. Only an
    # explicit amendment label establishes the more specific form.
    if kind == "legislative text" and any(re.fullmatch(
            r"(?:[\w’'.-]+\s+){0,5}Amendment\s+(?:to|fo)\s+(?:S\.|H\.?\s*R\.?)\s*\d+", label.strip(), re.I)
            for label in labels):
        kind, basis = "committee amendment", "publisher_link_label"
    # An amendment list may also link its summary. Keep that document form.
    if kind == "committee amendment" and any(re.fullmatch(
            r"(?:amendment )?summar(?:y|ies)", label.strip(), re.I) for label in labels):
        kind, basis = "summary", "publisher_link_label"
    primary_witness_file = any("Button--hearingLink" in (a.get("class") or "").split() for a in attributes)
    if not kind and primary_witness_file and (card or len(occurrence.get("witness_indexes") or []) == 1):
        urls = [a.get("href", "") for a in attributes]
        literal = literal_document_kind(" ".join(labels), " ".join(urls))
        # A biography, transcript or QFR can share the witness's card.
        if literal in {"other", "member statement", "witness statement"}:
            member = card.get("role") == "member"
            kind = "member statement" if member else "witness statement"
            basis = "publisher_member_card" if member else "publisher_witness_card"
    return kind, basis


def document_context(metadata):
    """Return a shared type only when all occurrences agree on it and its basis."""
    occurrences = (metadata or {}).get("occurrences") or [metadata or {}]
    results = [_document_occurrence_context(occurrence) for occurrence in occurrences]
    return results[0] if all(result == results[0] for result in results) else (None, None)


def document_kind(label, url, metadata=None):
    """Prefer publisher context to the legacy link-word inference."""
    return document_context(metadata)[0] or literal_document_kind(label, url)


def documents(page_html, url, metadata=None):
    """(kind, name, file) for each file a hearing page links. The name is the link's own words; under a button
    ("Download Testimony"), the heading it stands under, the witness or senator whose file it is; and the file's
    own name when the link is a picture."""
    if metadata is None:
        metadata, _, _ = source_details(page_html, url, witnesses(page_html, url))
    page_html, out = re.sub(r"<!--.*?-->", "", page_html, flags=re.S), {}
    for link, file in file_anchors(page_html, url):
        said = text(link.group(2))
        heading = re.findall(r"<h[2-5][^>]*>(.*?)</h[2-5]>", page_html[max(0, link.start() - 2500):link.start()], re.S)
        name = text(heading[-1]) if heading and re.match(r"(download|view|read|open)\b", said, re.I) else said or file.rsplit("/", 1)[-1]
        out.setdefault(file, (document_kind(said, file, metadata.get(file)), name, file))
    return list(out.values())


def text_lines(node):
    """Visible br-separated lines, with the anchors belonging to each line."""
    result = [dict(text='', anchors=[])]
    def visit(current):
        if not isinstance(current.tag, str) or current.tag in {'script', 'style'}:
            return
        if current.tag == 'br':
            result.append(dict(text='', anchors=[]))
            return
        if current.tag == 'a':
            result[-1]['anchors'].append(current)
        result[-1]['text'] += current.text or ''
        for child in current:
            visit(child)
            result[-1]['text'] += child.tail or ''
    visit(node)
    for line in result:
        line['text'] = ' '.join(line['text'].split())
    return result


def link_line(anchor):
    blocks = anchor.xpath('ancestor::p[1] | ancestor::li[1]')
    block = blocks[-1] if blocks else anchor
    return next((line for line in text_lines(block) if anchor in line['anchors']), dict(text='', anchors=[]))


def paragraph_headings(paragraph, anchor=None):
    """Bold labels on their own visual line also delimit a publisher section.

    EPW embeds these lines in paragraphs using repeated br tags. Inline emphasis
    in prose is not a heading. An inline label followed by links stays local to
    its paragraph and is handled separately by link_headings.
    """
    markup = dom.tostring(paragraph, encoding="unicode", with_tail=False)
    nodes = list(paragraph.iter())
    limit = nodes.index(anchor) if anchor is not None else len(nodes)
    result, start = [], 0
    # Some House templates put the exact section label on a br-separated
    # line, including inside one long italic/bold paragraph.
    for line in text_lines(paragraph):
        if anchor is not None and anchor in line['anchors']:
            break
        if not line['anchors'] and re.fullmatch(r'(?:witness(?:es| list)?|opening statements?)\s*:?', line['text'], re.I):
            heading = dom.Element('span')
            heading.text = line['text']
            result.append(heading)
    for node in paragraph.xpath(".//strong|.//b|.//u[not(.//strong or .//b)]"):
        written = dom.tostring(node, encoding="unicode", with_tail=False)
        position = markup.find(written, start)
        if position < 0:
            continue
        start = position + len(written)
        # A bold file title is not a new section. EPW's linked QFR heading
        # is an explicit section label and can name its own download.
        if node.xpath(".//a") and not section_document_kind({"headings": [" ".join(node.text_content().split())]}):
            continue
        before = re.split(r"<br\b[^>]*>", markup[:position])[-1]
        after = re.split(r"<br\b[^>]*>", markup[start:])[0]
        if nodes.index(node) < limit and not text(before) and not text(after):
            result.append(node)
    return result


def table_column_heading(anchor):
    """Use a simple document table's explicit column label, not nearby prose.

    Legacy House markup tables use td cells for their header row. Spans,
    irregular rows, or links in that row leave column ownership ambiguous.
    """
    cells = anchor.xpath('ancestor::*[self::td or self::th][1]')
    tables = anchor.xpath('ancestor::table[1]')
    if not cells or not tables or cells[0].getparent().tag != 'tr':
        return None
    cell, table = cells[0], tables[0]
    row = cell.getparent()
    rows = table.xpath('./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr')
    if row not in rows or row is rows[0]:
        return None
    header = rows[0].xpath('./th | ./td')
    if not header or rows[0].xpath('.//a'):
        return None
    for preceding in rows[:rows.index(row) + 1]:
        columns = preceding.xpath('./th | ./td')
        if len(columns) != len(header) or any(
                c.get('colspan', '1') != '1' or c.get('rowspan', '1') != '1' for c in columns):
            return None
    heading = ' '.join(header[row.xpath('./th | ./td').index(cell)].text_content().split())
    return heading if section_document_kind({'headings': [heading]}) else None


def link_headings(anchor, *, skip_panels=False):
    """Find the closest enclosing section's heading in DOM order.

    Foreign Relations and Aging wrap the heading in Hearing__sectionHeading.
    Do not cross a separate section, navigation region, or witness card to find
    a heading. An adjacent section's heading never describes this anchor.
    """
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
    branch = anchor
    for ancestor in anchor.iterancestors():
        headings = paragraph_headings(ancestor, anchor) if ancestor.tag == "p" else []
        # Indian Affairs places a bold label and several bill links in one
        # paragraph. Its label describes those files, not the next paragraph.
        inline = (ancestor.tag == "p" and not (ancestor.text or "").strip()
                  and len(ancestor) and ancestor[0].tag in {"strong", "b"})
        for sibling in ancestor:
            if sibling is branch:
                break
            if sibling.tag in heading_tags:
                headings.append(sibling)
            elif inline and sibling.tag in {"strong", "b"} and not sibling.xpath(".//a"):
                headings.append(sibling)
            elif set((sibling.get("class") or "").split()) & {"Hearing__sectionHeading", "Heading--sectionTitle"}:
                headings.extend(sibling.xpath("./h1|./h2|./h3|./h4|./h5|./h6"))
            elif "AdditionalContent" in (sibling.get("class") or "").split() and not sibling.xpath(".//a"):
                headings.extend(sibling.xpath("./div[contains(concat(' ', normalize-space(@class), ' '), ' Heading--sectionTitle ')]/h2"))
            elif sibling.tag == "p":
                headings.extend(paragraph_headings(sibling))
            elif sibling.tag == 'div' and not sibling.xpath('.//a') and re.fullmatch(
                    r'witness(?:es| list)?\s*:?', ' '.join(sibling.text_content().split()), re.I):
                headings.append(sibling)
        # Commerce introduces one amendment list with its bill/substitute.
        # The introduction does not describe links after that list.
        if branch.tag in {"ul", "ol"}:
            previous = branch.getprevious()
            while previous is not None and not isinstance(previous.tag, str):
                previous = previous.getprevious()
            if previous is not None and previous.tag in {"p", "li"} and AMENDMENT_LIST.fullmatch(
                    " ".join(previous.text_content().split())):
                headings.append(previous)
        headings = [node for node in headings if node.text_content().strip()]
        if skip_panels:
            headings = [node for node in headings if not re.fullmatch(
                r'panel\s*:?\s*(?:\d+|[ivx]+|one|two|three|four)\s*:?',
                ' '.join(node.text_content().split()), re.I)]
        if headings:
            # Inline tags can split a word ("Question<a>...</a>s") or precede
            # punctuation; keep the publisher's contiguous text intact.
            return [" ".join(headings[-1].text_content().split())]
        classes = set((ancestor.get("class") or "").split())
        if ancestor.tag in {"section", "article", "nav", "aside", "footer", "main"} or classes & {
                "Hearing__section", "vcard", "capigacr-widget-card", "paragraph--witness",
                "field-collection-item-field-hearing-new-witness", "jet-listing-grid__item"}:
            break
        if ancestor.tag in {'td', 'th'} and (heading := table_column_heading(anchor)):
            return [heading]
        branch = ancestor
    return []


def related_page(anchor, page_url):
    """Qualify a source link's purpose without asserting destination content.

    Document paths/fields designate a document page. A witness name or a
    repository points to relevant material but does not identify a file.
    """
    literal = anchor.get('href', '')
    if not literal.strip() or literal.strip().startswith('#') or anchor.xpath(
            'ancestor::nav | ancestor::aside | ancestor::footer | ancestor::*[@role="navigation" or @role="contentinfo"]'):
        return None
    target = http_url(literal, page_url)
    if not target:
        return None
    # Existing direct files keep their established occurrence context.
    if is_document_url(target, publisher_routes=True):
        return None
    parts = urlsplit(target)
    if parts.hostname == 'docs.house.gov' and re.fullmatch(
            r'/Committee/Calendar/By(?:Event|Day)\.aspx', parts.path, re.I):
        result = dict(url=target, role='repository', basis='publisher_repository_url')
        for key, values in parse_qs(parts.query).items():
            field = {'eventid': 'event_ids', 'dayid': 'day_ids'}.get(key.lower())
            if field:
                result.setdefault(field, []).extend(values)
        return result
    if (parts.hostname or '').endswith(('.house.gov', '.senate.gov')):
        match = re.fullmatch(r'/(witness-testimony|submission-for-the-record|hearing-transcript|opening-statement)/[^/]+/?', parts.path, re.I)
        if match:
            kind = {'witness-testimony': 'witness statement', 'submission-for-the-record': 'support document',
                    'hearing-transcript': 'transcript', 'opening-statement': 'member statement'}[match[1].lower()]
            return dict(url=target, role='document', document_kind=kind, basis='publisher_document_path')
    label = ' '.join(anchor.text_content().split())
    if re.fullmatch(r'watch\s+webcast', label, re.I):
        return dict(url=target, role='media', basis='publisher_media_label')
    if TRANSCRIPT_LABEL.fullmatch(label):
        return dict(url=target, role='document', document_kind='transcript', basis='publisher_document_label')
    headings = link_headings(anchor, skip_panels=True)
    witness_section = len(headings) == 1 and re.fullmatch(r'witness(?:es| list)?\s*:?', headings[0], re.I)
    submission_section = len(headings) == 1 and re.fullmatch(r'submissions? for (?:the )?record\s*:?', headings[0], re.I)
    # Field evidence must be local. Never inherit a role through a separate
    # section or override its heading with an outer witness container.
    for ancestor in anchor.iterancestors():
        classes = set((ancestor.get('class') or '').split())
        if ancestor.tag == 'p' and 'hearing-transcript' in classes:
            return dict(url=target, role='document', document_kind='transcript', basis='publisher_transcript_field')
        previous = ancestor.getprevious()
        marked_list = ('item-list' in classes and previous is not None and previous.tag == 'h2'
                       and 'migrated-submissions-record' in (previous.get('class') or '').split())
        if ((ancestor.get('id') == 'statement-for-the-record' or marked_list) and submission_section
                and parts.hostname == urlsplit(page_url).hostname and re.fullmatch(r'/node/\d+/?', parts.path)):
            return dict(url=target, role='document', document_kind='support document',
                        basis='publisher_submission_section', headings=headings)
        if (not headings or witness_section) and classes & {
                'view-id-max_witness_list', 'evo-hearing__field-evo-witnesses'}:
            return dict(url=target, role='witness_reference', basis='publisher_witness_field', headings=headings)
        if ancestor.tag in {'section', 'article', 'main'}:
            break
    if witness_section:
        return dict(url=target, role='witness_reference', basis='publisher_witness_section', headings=headings)
    return None


def plain_witness_links(root):
    """Explicit witness sections with a name on the link or its local line.

    A generic testimony button can refer to the immediately preceding paragraph
    only. Never search backwards across another paragraph or section. Keep the
    publisher's complete line; shared name parsing supplies the compact fields.
    """
    for anchor in root.xpath('.//a[@href]'):
        headings = link_headings(anchor)
        if len(headings) != 1 or not re.fullmatch(r'witness(?:es| list)?\s*:?', headings[0], re.I):
            continue
        label = ' '.join(anchor.text_content().split())
        candidates = [label]
        blocks = anchor.xpath('ancestor::li[1] | ancestor::p[1]')
        for block in reversed(blocks):
            if len(block.xpath('.//a[@href]')) != 1:
                continue
            line = ' '.join(block.text_content().split())
            candidates.append(line.removesuffix(label).rstrip(' -'))
            previous = block.getprevious()
            if (line == label and previous is not None and previous.tag == 'p'
                    and not previous.xpath('.//a[@href]')):
                candidates.append(' '.join(previous.text_content().split()))
        def named(line):
            name = witness(line)['name']
            return is_name(name) and all(word[:1].isupper() or word in {'de', 'del', 'van', 'von', 'da', 'di', 'la'} for word in name.split())
        line = next((line for line in candidates if named(line)), None)
        if line:
            yield anchor, line


def century_year(year: int) -> int:
    """Expand a 2-digit year for Senate inventory (~1935+): 35–99 → 1935–1999, 00–34 → 2000–2034."""
    if year > 99:
        return year
    return (1900 if year >= 35 else 2000) + year


def written_day(match):
    try:
        if match.group(1):
            return dt.date(century_year(int(match.group(3))), int(match.group(1)), int(match.group(2)))
        if match.group(4):
            return dt.date(int(match.group(6)), MONTHS.index(match.group(4)[:3].lower()) + 1, int(match.group(5)))
        return dt.date(int(match.group(7)), int(match.group(8)), int(match.group(9)))
    except ValueError:
        return None


def lines(page_html):
    """The lines of a page's text: what stands between one block's tag and the next."""
    page_html = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", " ", page_html, flags=re.S)
    return {text(l) for l in re.split(r"</?(?:div|p|li|ul|ol|h\d|tr|td|th|table|section|article|header|footer|nav|aside|main|form|dl|dt|dd|br)\b[^>]*>", page_html)} - {""}


def topic(title):
    """The subject of a Senate meeting title: "Hearings to examine improving veterans' employment ..." -> "improving veterans' employment ..."."""
    return re.sub(r"^\s*(an? )?(oversight |joint )*hearings? (to examine|to receive testimony on|on)\s+", "", re.sub(r"\s+", " ", title), flags=re.I)


def attachment_page(url):
    """Only explicit official-site attachment pages, never speculative URL swaps."""
    parsed = urlsplit(url)
    return parsed.hostname in ("drugcaucus.senate.gov", "www.drugcaucus.senate.gov") and parsed.path.startswith("/media-center/files/")


def event_type(title):
    """The first proceeding named by a title, excluding later agenda items."""
    proceeding = re.match(r"^\W*(?:(?:rescheduled|postponed|cancell?ed)\s*(?:[:)\]]\s*)+)?(?:(?:open|closed|joint|oversight|legislative|SCIA)\s+)*(roundtable|field hearing|business meeting|mark[ -]?up|briefing|hearing)\b", title, re.I)
    return proceeding.group(1).title().replace("Mark Up", "Markup").replace("Mark-Up", "Markup") if proceeding else None


def event_details(page_html, url):
    """Read a proceeding's own displayed title/date; publication dates are excluded.

    An event is admitted only from a recognized official hearing layout. Generic
    dates elsewhere in the page (menus, transcripts, publication metadata) cannot
    create a meeting. The source date stays unchanged if a curated correction is
    subsequently selected by the adapter.
    """
    host = urlsplit(url).hostname or ""
    if host.removeprefix("www.") not in SITE.values() or not re.search(r"/hearings/[^/]+", urlsplit(url).path):
        return None
    heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", page_html, re.S)
    if not heading:
        return None
    title = text(heading.group(1))
    # WordPress event templates explicitly mark the hearing date. The Drug
    # Caucus uses an unlabeled date immediately before the hearing heading.
    candidates = [text(value) for value in re.findall(r'<(?:div|p)[^>]*class="jet-listing-dynamic-field__content"[^>]*>(.*?)</(?:div|p)>', page_html, re.S)]
    date_text = next((value for value in candidates if re.match(r"^Date:\s*", value, re.I)), None)
    displayed_type = None
    if date_text is None and host.removeprefix("www.") == "csce.gov":
        root = dom.fromstring(page_html)
        dates = root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " csce-hearing__field-hearing-date ")]')
        if len(dates) == 1:
            date_text = text(dom.tostring(dates[0], encoding="unicode", with_tail=False))
    if date_text is None and host.removeprefix("www.") == "help.senate.gov":
        # The older HELP template labels its event date inside Hearing__details.
        # Keep its displayed type, rather than inferring one from the bill list.
        root = dom.fromstring(page_html)
        details = root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " Hearing__details ")]')
        if details:
            dates = details[0].xpath('.//time')
            if len(dates) == 1:
                date_text = text(dom.tostring(dates[0], encoding="unicode", with_tail=False))
                labels = root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " PageContent--pageTop ")]//*[contains(concat(" ", normalize-space(@class), " "), " Heading--overline ")]')
                if len(labels) == 1:
                    displayed_type = text(dom.tostring(labels[0], encoding="unicode", with_tail=False)) or None
    if date_text is None and host.removeprefix("www.") == "drugcaucus.senate.gov":
        before = page_html[max(0, heading.start() - 3000):heading.start()]
        values = re.findall(r'<(?:div|p)[^>]*class="jet-listing-dynamic-field__content"[^>]*>(.*?)</(?:div|p)>', before, re.S)
        date_text = next((text(value) for value in reversed(values) if DATE.fullmatch(text(value))), None)
    match = DATE.search(date_text or "")
    date = written_day(match) if match else None
    if not title or date is None:
        return None
    native_type = displayed_type or event_type(title) or "Meeting"
    if native_type == "Meeting" and re.search(r'\b(?:hold|held)\s+(?:a\s+)?field hearing titled', text(page_html[heading.end():heading.end() + 18000]), re.I):
        native_type = "Field Hearing"
    if native_type == "Meeting" and re.search(r'<body[^>]*class="[^"]*\bsingle-hearings\b', page_html):
        native_type = "Hearing"
    return {"title": title, "date": date.isoformat(), "date_text": date_text, "type": native_type, "url": url}


def document_labels(page_html, url):
    """Keep the provider's exact anchor words alongside our document category."""
    page_html = re.sub(r"<!--.*?-->", "", page_html, flags=re.S)
    return {target: text(link.group(2)) for link, target in file_anchors(page_html, url)}


def source_details(page_html, url, people, *, plain=False, include_link=None):
    if not page_html.strip():
        return {}, {}, {}
    root = dom.fromstring(page_html, parser=dom.HTMLParser(remove_comments=True))
    return source_details_tree(root, url, people, plain=plain, include_link=include_link)


def source_details_tree(root, url, people, *, plain=False, include_link=None):
    """Keep page content, links and explicit witness-card ownership.

    Existing witness rows and document triples remain unchanged for stable source
    identities. The indexes here refer to those rows. An ambiguous/repeated name
    is never enough to attach a document; it must be inside a recognized card
    containing exactly one already parsed witness.
    """
    def has(node, token):
        return token in (node.get("class") or "").split()
    def nodes(node, token):
        return [child for child in node.iter() if has(child, token)]
    def value(node):
        return text(dom.tostring(node, encoding="unicode", with_tail=False))
    # Matching uses a set of text lines; retained evidence must also preserve
    # paragraph/panel order and repeated text. Scripts and styles are not prose.
    blocks = {"div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "table",
              "section", "article", "header", "footer", "nav", "aside", "main", "form", "dl", "dt", "dd", "br"}
    def visible(node):
        if not isinstance(node.tag, str) or node.tag.lower() in ("script", "style"):
            return
        if node.tag in blocks:
            yield "\n"
        yield node.text or ""
        for child in node:
            yield from visible(child)
            yield child.tail or ""
        if node.tag in blocks:
            yield "\n"
    ordered = [re.sub(r"\s+", " ", line).strip() for line in "".join(visible(root)).splitlines()]
    page_metadata = {"text": "\n".join(line for line in ordered if line)}
    media = [{"tag": node.tag, "attributes": dict(node.attrib)} for node in root.iter()
             if node.tag in ("iframe", "video", "audio", "source", "track", "object", "embed")]
    if media:
        page_metadata["media"] = media
    for field, class_name in (("video_messages", "Hearing__videoMessageContent"),
                              ("heading_prefixes", "Hearing__headingPrefix")):
        values = [{"text": value(node), "attributes": dict(node.attrib)} for node in nodes(root, class_name)]
        if values:
            page_metadata[field] = values
    # Non-visible descriptions and structured data can contain meeting facts.
    meta = [dict(node.attrib) for node in root.xpath(".//meta") if
            "description" in (node.get("name") or node.get("property") or "").lower()
            or "video" in (node.get("name") or node.get("property") or "").lower()]
    if meta:
        page_metadata["meta"] = meta
    structured = [node.text or "" for node in root.xpath(".//script[@type='application/ld+json']")]
    if structured:
        page_metadata["structured_data"] = structured
    # HSGAC/Indian pages build their player from separate inline assignments.
    # Keep the original configuration, timing code and iframe template together;
    # none is executed or turned into an asserted recording URL.
    scripts = root.xpath(".//script[not(@src)]")
    if any(re.search(r"\barchive_stream\s*=", node.text or "") for node in scripts):
        page_metadata["media_scripts"] = [
            {"attributes": dict(node.attrib), "text": node.text or ""} for node in scripts
            if re.search(r"\b(?:archive_stream|archive_offset|originalTimestamp|live_starttime|comm_code|posterframe)\b", node.text or "")]
    by_name = {}
    for index, row in enumerate(people):
        by_name.setdefault(row["name"], []).append(index)
    cards = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        family = next((token for token in ("capigacr-widget-card", "vcard", "paragraph--witness",
            "field-collection-item-field-hearing-new-witness", "jet-listing-grid__item") if has(node, token)), None)
        if not family and node.tag == "li" and len(nodes(node, "witness-content")) == 1:
            family = "witness-content"
        if not family and node.tag == "li" and has(node, "list-group-item") and (nodes(node, "full-name") or nodes(node, "person")):
            family = "list-group-item"
        if family:
            cards.append((node, family))
    witnesses_by_node, witness_metadata, cards_by_node = {}, {}, {}
    for card, family in cards:
        selectors = {"capigacr-widget-card": "capigacr-widget-card__title", "vcard": "fn",
                     "paragraph--witness": "witness__field-name", "field-collection-item-field-hearing-new-witness": "group-header",
                     "list-group-item": "full-name"}
        if family in selectors:
            names = nodes(card, selectors[family])
            if not names and family == "list-group-item":
                names = nodes(card, "person")
            raw_name = " ".join(value(node) for node in names)
            if family == "vcard":
                raw_name = " ".join(value(node) for node in nodes(card, "honorific-prefix")) + " " + raw_name
        elif family == "jet-listing-grid__item":
            raw_name = " ".join(value(node) for node in card.iter() if node.tag in ("h3", "h4") and has(node, "jet-listing-dynamic-field__content"))
        else:
            headings = card.xpath(".//h2|.//h3|.//h4|.//h5")
            above = card.xpath(".//p")
            raw_name = value(headings[-1]) if headings else (value(above[0]) if above else "")
            raw_name = re.sub(r"^\d+\.\s*", "", raw_name)
        matches = by_name.get(witness(raw_name)["name"], []) if raw_name.strip() else []
        if not raw_name.strip():
            continue
        fields = []
        field_classes = {"title", "org", "occupation", "organization", "member-detail-item", "locality", "region",
                         "witness__field-position", "witness__field-organization", "jet-listing-dynamic-field__content"}
        for node in card.iter():
            parent = node.getparent()
            if isinstance(node.tag, str) and (set((node.get("class") or "").split()) & field_classes or
                    (parent is not None and has(parent, "witness-content")) or node.tag == "em"):
                if written := value(node):
                    fields.append({"class": node.get("class", ""), "text": written})
        metadata = {"layout": family, "name": raw_name.strip(), "text": value(card), "attributes": dict(card.attrib), "fields": fields}
        for ancestor in card.iterancestors():
            if has(ancestor, "Hearing__additionalContentSection--members"):
                metadata["role"] = "member"
            if has(ancestor, "capigacr-widget-card__panel-section"):
                headings = nodes(ancestor, "capigacr-widget-card__panel-section-title")
                if len(headings) == 1:
                    metadata["panel"] = value(headings[0])
                break
        location = next((field["text"] for field in fields if field["class"] in ("locality", "region") or
                         re.fullmatch(r"[^,]+,\s*[A-Z]{2}(?:\s+\d{5})?", field["text"])), None)
        if location:
            metadata["location"] = location
        cards_by_node[card] = metadata
        if len(matches) == 1:
            index = matches[0]
            witness_metadata[str(index)] = metadata
            witnesses_by_node[card] = index
    if plain:
        for anchor, line in plain_witness_links(root):
            if any(parent in cards_by_node for parent in anchor.iterancestors()):
                continue
            metadata = dict(layout='plain-witness-line', name=line, text=line, attributes=dict(anchor.attrib), fields=[])
            cards_by_node[anchor] = metadata
            matches = by_name.get(witness(line)['name'], [])
            if len(matches) == 1:
                witnesses_by_node[anchor] = matches[0]
                witness_metadata[str(matches[0])] = metadata
    # Separate cards with the same parsed name are not proof that their people
    # are identical. The older witness list may already have deduplicated names.
    repeated = {index for index, count in Counter(witnesses_by_node.values()).items() if count > 1}
    witnesses_by_node = {card: index for card, index in witnesses_by_node.items() if index not in repeated}
    witness_metadata = {index: metadata for index, metadata in witness_metadata.items() if int(index) not in repeated}
    files, file_nodes = {}, set()
    for anchor in root.xpath(".//a[@href]"):
        if not http_url(anchor.get('href', ''), url):
            continue
        href = urljoin(url, anchor.get("href", "").strip(' '))
        if not is_document_url(href, publisher_routes=True) and not (include_link and include_link(anchor)):
            continue
        if feed_link(anchor, href):
            continue
        file_nodes.add(anchor)
        entry = files.setdefault(href, {"labels": [], "attributes": [], "container_attributes": [], "witness_indexes": [], "occurrences": []})
        label = value(anchor)
        occurrence = {"labels": [label] if label else [], "attributes": [dict(anchor.attrib)],
                      "container_attributes": [], "witness_indexes": [], "headings": link_headings(anchor)}
        if related := related_page(anchor, url):
            occurrence['related_page'] = related
        paragraphs = anchor.xpath("ancestor::p[1]")
        if paragraphs and (paragraph := " ".join(paragraphs[0].text_content().split())):
            occurrence["paragraph_text"] = paragraph
        if plain and (line := link_line(anchor)['text']):
            occurrence['line_text'] = line
        if label and label not in entry["labels"]:
            entry["labels"].append(label)
        attributes = dict(anchor.attrib)
        if attributes not in entry["attributes"]:
            entry["attributes"].append(attributes)
        # The closest card wins; retain each anchor separately so two anchors
        # for one URL cannot cross-pair their labels and witness ownership.
        for ancestor in [anchor, *anchor.iterancestors()]:
            attributes = {key: value for key, value in ancestor.attrib.items() if key.startswith("data-")}
            if has(ancestor, "witness__field-testimony"):
                attributes["class"] = ancestor.get("class")
            if attributes and attributes not in occurrence["container_attributes"]:
                occurrence["container_attributes"].append(attributes)
            if ancestor in cards_by_node:
                occurrence["witness_card"] = cards_by_node[ancestor]
                if ancestor in witnesses_by_node:
                    occurrence["witness_indexes"].append(witnesses_by_node[ancestor])
                break
        for field in ("container_attributes", "witness_indexes"):
            for item in occurrence[field]:
                if item not in entry[field]:
                    entry[field].append(item)
        entry["occurrences"].append(occurrence)
    # Non-file links can identify bills, nominations or witness organizations.
    # Retain literal destinations and explicit publisher roles without following them.
    page_metadata['links'] = []
    for anchor in root.xpath('.//a[@href]'):
        if anchor in file_nodes:
            continue
        entry = dict(text=value(anchor), attributes=dict(anchor.attrib))
        if related := related_page(anchor, url):
            entry['related_page'] = related
        page_metadata['links'].append(entry)
    return files, witness_metadata, page_metadata

"""Pure parsing for Senate/joint sites: seven witness layouts and linked files.

Witness headings exclude senators' statements. JEC running text is not interpreted. Listings
locate pages; only a page's own date and subject establish which meeting it is.
"""
import datetime as dt, html, re
from urllib.parse import urljoin, urlsplit

from congress_api.witnesses import is_name, witness
from congress_api.inventory.common import text

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
## a file a page links, and what its link or name says it is
FILE = re.compile(r"<a\b[^>]*href=\"([^\"]*(?:/download/|/media-center/files/|/wp-content/uploads/|/_cache/files/|/imo/media/doc/|/services/files/|/sites/[^\"]*/files/|files\.serve|\.pdf)[^\"]*)\"[^>]*>(.*?)</a>", re.S | re.I)
KINDS = [("transcript", r"transcript"), ("questions for the record", r"qfr|questions?[ \-_]for[ \-_]the[ \-_]record|responses?[ \-_]to[ \-_](?:written[ \-_])?questions"),
         ("questionnaire", r"questionnaire"), ("witness biography", r"\bbio(?:graphy)?\b|/bio_"), ("witness statement", r"testimony"), ("member statement", r"statement")]



def person(name, details, page):
    """One witness row from a name as the page writes it ("The Honorable Jay Bhattacharya, M.D., Ph.D.") and the lines under it."""
    details = [d for d in (text(d) for d in details) if d and not re.match(r"(download|view|watch) ", d, re.I)]
    return {"name": witness(text(name))["name"], "position": details[0] if details else "", "organization": ", ".join(details[1:3]), "page": page}


def sections(page_html, levels):
    """The page cut at its headings, less the sections headed as statements or remarks: the senators', laid out like witnesses."""
    return [s for s in re.split(rf"(?=<h[{levels}]\b)", page_html) if not (s.startswith("<h") and re.search(r"statement|remarks", text(s.split("</h")[0]), re.I))]


def witnesses(page_html, url):
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
    seen = set()
    return [w for w in out if is_name(w["name"]) and not (w["name"] in seen or seen.add(w["name"]))]


def documents(page_html, url):
    """(kind, name, file) for each file a hearing page links. The name is the link's own words; under a button
    ("Download Testimony"), the heading it stands under, the witness or senator whose file it is; and the file's
    own name when the link is a picture."""
    page_html, out = re.sub(r"<!--.*?-->", "", page_html, flags=re.S), {}
    for link in FILE.finditer(page_html):
        file = html.unescape(link.group(1)).strip()
        if re.search(r"\.(jpe?g|png|gif|svg|css|js|ico)($|\?)", file, re.I):
            continue
        file = urljoin(url, file)
        said = text(link.group(2))
        heading = re.findall(r"<h[2-5][^>]*>(.*?)</h[2-5]>", page_html[max(0, link.start() - 2500):link.start()], re.S)
        name = text(heading[-1]) if heading and re.match(r"(download|view|read|open)\b", said, re.I) else said or file.rsplit("/", 1)[-1]
        out.setdefault(file, (next((k for k, pattern in KINDS if re.search(pattern, f"{said} {file.rsplit('/', 1)[-1]}", re.I)), "other"), name, file))
    return list(out.values())


def written_day(match):
    try:
        if match.group(1):
            year = int(match.group(3))
            return dt.date(year if year > 99 else 2000 + year, int(match.group(1)), int(match.group(2)))
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
    if date_text is None and host.removeprefix("www.") == "drugcaucus.senate.gov":
        before = page_html[max(0, heading.start() - 3000):heading.start()]
        values = re.findall(r'<(?:div|p)[^>]*class="jet-listing-dynamic-field__content"[^>]*>(.*?)</(?:div|p)>', before, re.S)
        date_text = next((text(value) for value in reversed(values) if DATE.fullmatch(text(value))), None)
    match = DATE.search(date_text or "")
    date = written_day(match) if match else None
    if not title or date is None:
        return None
    native_type = event_type(title) or "Meeting"
    if native_type == "Meeting" and re.search(r'\b(?:hold|held)\s+(?:a\s+)?field hearing titled', text(page_html[heading.end():heading.end() + 18000]), re.I):
        native_type = "Field Hearing"
    if native_type == "Meeting" and re.search(r'<body[^>]*class="[^"]*\bsingle-hearings\b', page_html):
        native_type = "Hearing"
    return {"title": title, "date": date.isoformat(), "date_text": date_text, "type": native_type, "url": url}


def document_labels(page_html, url):
    """Keep the provider's exact anchor words alongside our document category."""
    return {urljoin(url, html.unescape(link.group(1)).strip()): text(link.group(2)) for link in FILE.finditer(page_html)}

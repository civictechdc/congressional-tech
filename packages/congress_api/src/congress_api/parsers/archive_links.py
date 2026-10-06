"""Find explicit related files in supplied source data; never crawl navigation."""

import ipaddress
import json
import re
from urllib.parse import parse_qsl, urlsplit

from lxml import etree
from lxml.html.defs import tags as HTML_TAGS

from congress_api.models.content import content_bytes
from congress_api.parsers.senate import parse_page as parse_senate_page
from congress_api.parsers.pdf_tools import readable_pdf
from congress_api.parsers.file_wrapper import regular_file
from congress_api.parsers.image_tools import image_kind, image_info, ImageReadError

from congress_api.parsers.document_links import (
    document_links,
    http_url,
    FILE,
    response_kind,
)

MEDIA_FILE = re.compile(r"\.(?:mp4|m4v|webm|mov|mp3|m4a|aac|ts|m4s)(?:$|[?#])", re.I)
SECRET_KEYS = {"api_key", "apikey", "key", "token", "access_token", "authorization"}


def inspect_capture(response, *, replay=False):
    """Classify retained source bytes using the same rules for fallback and capture."""
    body = (
        content_bytes(response["content"])
        if response.get("content") else b""
    )
    links = []
    if response.get("error") == "retained_body_limit":
        return "inspection_deferred", links
    if response.get("error") in {"response_limit", "source_response_limit", "provider_response_limit"}:
        return ("resource_limit" if response.get('body_limit_basis') == 'resource_budget'
                else "size_limit"), links
    if response.get("error") in {"timeout", "Timeout", "ReadTimeout", "ConnectTimeout"}:
        return "timeout", links
    if response.get("error") or not response.get("complete"):
        return "incomplete" if body else "request_failed", links
    if response.get("http_status") != 200 and not (
        replay and response.get("http_status") is None
    ):
        return "http_error", links
    outcome, kind = inspect_body(
        body, response["url"], response.get("content", {}).get("media_type", "")
    )
    if outcome in {"saved", "html"}:
        try:
            diagnostics = []
            links = related_links(body, response["url"], kind, diagnostics=diagnostics)
            if diagnostics:
                response['link_interpretation_warnings'] = diagnostics
        except (ValueError, UnicodeError) as error:
            response["interpretation_error"] = type(error).__name__
            outcome = "parse_failed"
    if outcome == "html" and links:
        outcome = "saved"
    return outcome, links


def allowed_url(value, base=""):
    url = http_url(value, base) if isinstance(value, str) else None
    if not url or MEDIA_FILE.search(url):
        return None
    parts = urlsplit(url)
    # Concatenated publisher fields and their redirects are retained as evidence,
    # but are not one download URL. Query parameters may contain valid URLs.
    if re.search(r"https?:/+", parts.path, re.I):
        return None
    host = parts.hostname.lower()
    if host in {
        "localhost",
        "metadata.google.internal",
        "api.zyte.com",
        "api.congress.gov",
        "api.govinfo.gov",
        "www.googleapis.com",
        "youtube.googleapis.com",
    } or host.endswith((".local", ".internal")):
        return None
    if any(k.lower() in SECRET_KEYS for k, _ in parse_qsl(parts.query)):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
    return url


def capture_links(item, base=""):
    """Admit one URL, or recover explicit file URLs from two known source defects.

    Transport still accepts only a single allowed URL. Repairs retain the literal
    source value and never guess a scheme, host, filename or document version.
    """
    value = item.get('url')
    if target := allowed_url(value, base):
        return [{**item, 'url': target}]
    if not isinstance(value, str) or re.search(r'[\s?#]', value):
        return []  # Query/fragment boundaries and whitespace are ambiguous.
    wrapper = re.fullmatch(r'https?://(?:www\.)?lis\.gov/cgi-lis/t2GPO/(https?://.+)', value, re.I)
    if wrapper:
        targets = [wrapper[1]]
        if not allowed_url(targets[0]):
            return []
        inner = urlsplit(targets[0])
        if inner.hostname not in {'gpo.gov', 'www.gpo.gov'} or not inner.path.startswith('/fdsys/pkg/'):
            return []
        reason = 'lis_gpo_wrapper'
    else:
        targets = re.split(r'(?=https?://)', value, flags=re.I)
        if targets[0] == '':
            targets.pop(0)
        if len(targets) < 2:
            return []
        reason = 'concatenated_file_urls'
    # All parts must be complete, independently allowed document URLs. Refuse
    # the entire repair if any part is malformed, private, credentialed or media.
    if not all(allowed_url(target) == target and FILE.search(target) for target in targets):
        return []
    return [{**item, 'url': target, 'original_url': value,
             'url_repair': reason, 'url_position': position}
            for position, target in enumerate(targets)]


def json_links(value, source="", pointer=(), context=None):
    for item in _json_links(value, source, pointer, context):
        yield from capture_links(item)


def _json_links(value, source="", pointer=(), context=None):
    """Read native document/link slots and literal file URLs, preserving source fields."""
    context = context or {}
    if isinstance(value, dict):
        if "eventId" in value:
            context = {
                k: value[k]
                for k in (
                    "eventId",
                    "congress",
                    "chamber",
                    "committees",
                    "title",
                    "date",
                    "type",
                )
                if k in value
            }
        for key, child in value.items():
            if key in {"body", "httpResponseBody", "raw_html", "raw_xml", "text"}:
                continue
            if (
                isinstance(child, dict)
                and allowed_url(key)
                and any(k in child for k in ("documents", "witnesses", "event"))
            ):
                yield {
                    "url": key,
                    "source": source,
                    "pointer": list(pointer),
                    "context": context,
                }
            if (
                isinstance(child, str)
                and capture_links({'url': child})
                and (
                    FILE.search(child)
                    or re.search(r"\.(?:vtt|srt|m3u8)(?:$|[?#])", child, re.I)
                    or (
                        key in {"url", "doc-url"}
                        and any("document" in str(p).lower() for p in pointer)
                    )
                )
            ):
                yield {
                    "url": child,
                    "source": source,
                    "pointer": [*pointer, key],
                    "context": context,
                    "native": {
                        k: v
                        for k, v in value.items()
                        if k not in {"body", "httpResponseBody"}
                    },
                }
            elif isinstance(child, (dict, list)):
                yield from _json_links(child, source, (*pointer, key), context)
    elif isinstance(value, list):
        # Existing House/Senate parsed state uses [type, label, URL, ...].
        if (
            len(value) >= 3
            and isinstance(value[2], str)
            and capture_links({'url': value[2]})
            and any("document" in str(p).lower() for p in pointer)
        ):
            yield {
                "url": value[2],
                "source": source,
                "pointer": list(pointer),
                "context": context,
                "native": value,
            }
        else:
            for index, child in enumerate(value):
                if (
                    isinstance(child, str)
                    and capture_links({'url': child})
                    and (
                        FILE.search(child)
                        or re.search(r"\.(?:vtt|srt|m3u8)(?:$|[?#])", child, re.I)
                    )
                ):
                    yield {
                        "url": child,
                        "source": source,
                        "pointer": [*pointer, index],
                        "context": context,
                    }
                else:
                    yield from _json_links(child, source, (*pointer, index), context)


def related_links(body, url, kind, *, diagnostics=None):
    if kind == "html":
        links = {
            candidate['url']: candidate
            for link in document_links(body, url)
            for candidate in capture_links(link.source_dict())
        }
        host = urlsplit(url).hostname or ""
        if host == "senate.gov" or host.endswith(".senate.gov"):
            try:
                page = parse_senate_page(body, url)
            except UnicodeError as exc:
                # The Senate source reader requires UTF-8. Keep generic links
                # from HTML with another encoding and retain the enrichment gap.
                if diagnostics is not None:
                    diagnostics.append({'reader': 'senate', 'error_type': type(exc).__name__})
                return list(links.values())
            for document_kind, label, target in page.documents:
                metadata = page.document_metadata.get(target)
                # Keep every literal occurrence, including distinct witness and
                # section context, while scheduling a URL only once.
                for candidate in capture_links({"url": target, "basis": "senate_document",
                    "text": label, "context": {"document_kind": document_kind,
                        "document_metadata": metadata.source_dict() if metadata else {}}}):
                    links[candidate['url']] = {**links.get(candidate['url'], {}), **candidate}
        return list(links.values())
    if kind == "xml":
        tree = etree.fromstring(
            body, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
        result = []
        for node in tree.iter():
            if not isinstance(node.tag, str):
                continue
            tag = etree.QName(node).localname
            values = [
                v
                for k, v in node.attrib.items()
                if etree.QName(k).localname in {"href", "doc-url", "url"}
            ]
            if tag.lower() in {"url", "uri"} and node.text:
                values.append(node.text.strip())
            for value in values:
                result.extend(capture_links(
                    {"url": value, "basis": "xml_link", "tag": tag,
                     "text": "".join(node.itertext()), "attributes": dict(node.attrib),
                     "source_xpath": tree.getroottree().getpath(node)}, url))
        return result
    if kind == "json":
        return list(json_links(json.loads(body), url))
    if kind == "playlist":
        # Only subtitle playlists/segments, never audio or video segments.
        result = []
        for line in body.decode("utf-8-sig").splitlines():
            match = (
                re.search(r'URI="([^"]+)"', line)
                if line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES")
                else None
            )
            value = (
                match[1]
                if match
                else line
                if re.search(r"\.(?:vtt|srt)(?:$|[?#])", line)
                and not line.startswith("#")
                else None
            )
            if value and (target := allowed_url(value, url)):
                result.append({"url": target, "basis": "subtitle_link", "text": line})
        return result
    return []


def inspect_body(body, url, media):
    """Basic format validation is distinct from a complete substantive document."""
    kind = response_kind(body, media)
    prefix = body[:8192].lower()
    if not body:
        return "empty", kind
    if any(
        marker in prefix
        for marker in (
            b"cf-chl-",
            b"<title>just a moment",
            b"verify you are human",
            b"<title>access denied",
        )
    ):
        return "challenge", "html"
    if media.lower().startswith(("video/", "audio/")):
        return "excluded_media", kind
    if image := image_kind(body):
        try:
            image_info(body)
        except ImageReadError:
            return 'invalid_document', image
        return 'saved', image
    if kind == "pdf":
        return ("saved" if b"%%EOF" in body[-8192:] or readable_pdf(body)
                else "invalid_document"), kind
    if kind == "file_wrapper":
        try:
            regular_file(body)
        except ValueError:
            return "unsupported_format", kind
        return "saved", kind
    if kind == "html":
        return "html", kind
    xml_hint = (
        kind == "xml"
        or urlsplit(url).path.lower().endswith(".xml")
        or media.split(";")[0] in {"application/xml", "text/xml"}
    )
    # XML declarations and correct response headers are optional in practice.
    # Infer XML only from a complete parse, never from a partial probe's prefix.
    markup = prefix.lstrip(b"\xef\xbb\xbf \t\r\n").startswith((b"<", b"\xff\xfe", b"\xfe\xff"))
    if xml_hint or markup:
        try:
            root = etree.fromstring(
                body, parser=etree.XMLParser(resolve_entities=False, no_network=True)
            )
        except etree.XMLSyntaxError:
            if xml_hint:
                return "invalid_document", "xml"
        else:
            name = etree.QName(root)
            html_fragment = name.namespace == "http://www.w3.org/1999/xhtml" or (
                not name.namespace and name.localname.lower() in HTML_TAGS
            )
            if xml_hint or not html_fragment:
                return "saved", "xml"
    if body.lstrip().startswith((b"{", b"[")) and (
        "json" in media or urlsplit(url).path.endswith(".json")
    ):
        try:
            json.loads(body)
            return "saved", "json"
        except (ValueError, UnicodeError):
            return "invalid_document", "json"
    if body.lstrip(b"\xef\xbb\xbf").startswith(b"#EXTM3U"):
        return "saved", "playlist"
    if kind in {"zip", "legacy_office", "rtf"} or body.lstrip(
        b"\xef\xbb\xbf"
    ).startswith(b"WEBVTT"):
        return "saved", kind
    if (
        media.split(";")[0].startswith(("text/plain", "text/csv", "text/vtt"))
        and b"\0" not in body[:8192]
    ):
        return "saved", "text"
    return "unverified", kind

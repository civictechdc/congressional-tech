"""Classify captured responses with the shared fallback and capture rules.

Bodies are checked with bounded readers. An owned response file is read only as
far as a rule needs; related links still come from the shared source parsers.
"""

import json
from urllib.parse import urlsplit

from lxml import etree
from lxml.html.defs import tags as HTML_TAGS

from congress_api.parsers.archive_links import capture_links, related_links
from congress_api.parsers.document_links import download_query_fallback, response_kind
from congress_api.parsers.file_wrapper import regular_file
from congress_api.retention.body_files import CapturedFile, content_body
from congress_api.retention.image_tools import image_kind, image_info, ImageReadError
from congress_api.retention.pdf_tools import readable_pdf


def inspect_capture(response, *, replay=False):
    """Classify retained source bytes using the same rules for fallback and capture."""
    body = (
        content_body(response["content"])
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
        fallback = download_query_fallback(response['url'], response.get('http_status'))
        return "http_error", capture_links(fallback.source_dict()) if fallback else []
    if isinstance(body, CapturedFile):
        # Ordinary complete PDFs need only the existing signature/EOF checks.
        # Other formats and malformed PDFs keep the existing bounded parsers.
        prefix = body.prefix()
        media = response.get('content', {}).get('media_type', '')
        if response_kind(prefix, media) == 'pdf':
            with body.path.open('rb') as source:
                source.seek(max(0, len(body) - 8192))
                tail = source.read(8192)
            if b'%%EOF' in tail:
                return inspect_body(prefix + tail, response['url'], media)[0], []
        body = body.read_bytes()
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

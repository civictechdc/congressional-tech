"""Route retained evidence by its source URL and source-file context."""

import re
from urllib.parse import parse_qsl, urlsplit


def family(source="", url="", pointer=(), media_type=""):
    """Route by explicit URL/layout evidence; an unknown source stays unknown."""
    path = str(source).lower()
    try:
        u = urlsplit(url if isinstance(url, str) else "")
    except ValueError:
        u = urlsplit("")
    host, upath = (u.hostname or "").lower(), u.path.lower()
    ptr = "/".join(map(str, pointer)).lower()
    combined = f"{path} {ptr}"
    if (
        host == "api.zyte.com"
        or "provider_response" in ptr
        or "/zyte/transport" in path
    ):
        return "external/provider-responses"
    if host in {"web.archive.org", "archive.org"}:
        return "external/wayback"
    if (
        "/legacy-web/" in path
        or "/hearing-text/search/" in path
        or host.endswith(("c-span.org", "bing.com", "google.com"))
    ):
        return "external/provider-responses"
    if "legislators" in combined or "congress-legislators" in upath:
        return "external/legislators"
    if host == "api.congress.gov":
        if "/committee-meeting/" in upath:
            return "congress/meetings"
        if "/committee/" in upath:
            return "congress/committees"
        return "documents"
    if "googleapis.com" in host and "/youtube/" in upath:
        return "youtube/api"
    if "youtube" in host or "googlevideo.com" in host:
        if "timedtext" in upath or "caption" in ptr:
            return "youtube/captions"
        return "youtube/watch-pages"
    if host.endswith("govinfo.gov") or host.endswith("gpo.gov"):
        if "mods" in upath:
            return "govinfo/mods"
        if "premis" in upath:
            return "govinfo/premis"
        if "mets" in upath:
            return "govinfo/mets"
        if "/html/chrg-" in upath:
            return "govinfo/transcript-html"
        return "documents"
    if host == "docs.house.gov":
        if upath.endswith(".xml"):
            return (
                "house/witness-xml"
                if "-wlist-" in upath
                else "house/meeting-xml"
                if "/hmtg-" in upath
                else "documents"
            )
        if "/committee/" in upath or "byevent.aspx" in upath:
            return "house/pages"
        return "documents"
    if host.endswith(".house.gov") or host == "house.gov":
        return (
            "documents"
            if re.search(r"\.(pdf|xml|docx?|zip|rtf)$", upath)
            else "house/pages"
        )
    if host.endswith("senate.gov") or "senate-gov" in host:
        if "caption" in combined or upath.endswith(".vtt"):
            return "senate/captions"
        if "/isvp" in upath or upath.endswith(".m3u8") or "akamaized.net" in host:
            return "senate/players"
        query = {k.casefold(): v.casefold() for k, v in parse_qsl(u.query)}
        if query.get("a") == "files.serve" and query.get("file_id"):
            return "documents"
        if "/wp-json/" in upath or any(
            x in u.query.lower() for x in ("pagenum_", "mt_page=", "page=")
        ):
            return "senate/listings"
        if any(x in upath for x in ("/download/", "/services/files/", "/imo/", "/uploads/")) or re.search(
            r"\.(pdf|xml|docx?|zip|rtf)$", upath
        ):
            return "documents"
        return "senate/pages"
    if re.search(r"\.(pdf|zip|docx?|rtf|xlsx?|xml|xsl|xslt)$", upath):
        return "documents"
    if re.search(r"/chrg-[^/]+\.html?(\.gz)?$", path):
        return "govinfo/transcript-html"
    if re.search(r"/crpt-[^/]+\.html?(\.gz)?$", path):
        return "documents"
    if (
        "congress_committees" in path
        or "committees.roundtrip" in path
        or "/committee-119." in path
    ):
        return "congress/committees"
    if any(
        x in path
        for x in (
            "congress_meetings",
            "meetings.roundtrip",
            "native-live",
            "/meetings.jsonl",
            "congress-api/meetings",
        )
    ):
        return "congress/meetings"
    if "youtube" in combined:
        if (
            "caption" in combined
            or "/tracks/" in path
            or path.endswith((".vtt", ".txt", ".none"))
        ):
            return "youtube/captions"
        if "/metadata/" in path or "watch" in path:
            return "youtube/watch-pages"
        return "youtube/api"
    if "senate" in combined:
        if "caption" in combined or path.endswith((".vtt", ".cues.txt", ".txt")):
            return "senate/captions"
        if "player" in combined or "recordings" in path or path.endswith(".m3u8"):
            return "senate/players"
        if "listing" in combined:
            return "senate/listings"
        return "senate/pages"
    if "house" in combined:
        if (
            "witness_xml" in combined
            or "/wlist/" in path
            or "/wlist_none_before_fix/" in path
        ):
            return "house/witness-xml"
        if (
            "meeting_xml" in combined
            or (
                "docs_house_xml" in path
                and ("/meeting/" in path or "/meeting_none_before_fix/" in path)
            )
            or path.endswith("house.json.gz")
        ):
            return "house/meeting-xml"
        if (
            path.endswith((".html", ".html.gz", ".aspx"))
            or "page_html" in ptr
            or "docs_house/" in path
        ):
            return "house/pages"
    if "premis" in combined:
        return "govinfo/premis"
    if "mets" in combined:
        return "govinfo/mets"
    if "mods" in combined or "gpo-xml" in path:
        return "govinfo/mods"
    if "gpo_html" in path or "/gpo/" in path or "transcript_html" in combined:
        return "govinfo/transcript-html"
    if any(
        x in combined
        for x in (
            "/documents/",
            "witness-pdf",
            "/witness_lists/",
            "/downloads/",
            "/xml_path_families/",
            "/pdf_xml_probe/",
        )
    ):
        return "documents"
    if re.search(r"\.(pdf|zip|docx?|rtf|xlsx?|xml|xsl|xslt)(\.gz)?$", path):
        return "documents"
    if host:
        return "external/provider-responses"
    return None

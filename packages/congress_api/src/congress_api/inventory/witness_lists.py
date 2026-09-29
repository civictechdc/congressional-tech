"""Fill missing witnesses from MODS and attached witness-list PDFs.

Keep original MODS/PDF bytes beside typed names, source text, URL, version and
check date, including valid empty lists. MODS uses GPO's parser, and PDFs use pypdf reading order.
The research used pdftotext; fixtures and the full seeded comparison check the
change in text extraction. Bad responses are failures, not scanned lists.
"""
import io
import hashlib
import datetime as dt
import re
from xml.etree.ElementTree import ParseError

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from congress_api import http
from congress_api.gpo.fetch import GOVINFO_CONTENT, mods_witnesses
from congress_api.inventory.common import due
from congress_api.witnesses import TITLE, DEGREE, is_name, witness
from congress_api.inventory.reviewed_witness_lists import REVIEWED
from congress_api.models.content import RawContent
from congress_api.models.documents import DocumentWitness, PdfTextPage, PdfWitnessObservation, ModsWitnessObservation
from congress_api.gpo.source import parse_mods_document

PARSER_VERSION = 2


def parse_document_witnesses(text: str) -> list[DocumentWitness]:
    out, current = [], None
    for line in (line.strip() for line in text.splitlines()):
        title = TITLE.match(line + " ")
        # Academic credentials explicitly mark a personal name even when its
        # source omitted an honorific. Other unmarked lines remain unparsed.
        suffix = line.rsplit(",", 1)[-1].strip()
        credential = "," in line and DEGREE.fullmatch(suffix) and ("." in suffix or suffix.lower() in ("phd", "edd", "psyd", "pharmd", "scd"))
        name = witness(line)["name"].rstrip("*†‡ ") if title or credential else ""
        if is_name(name) and len(line.split()) <= 8 and not line.endswith(":"):
            current = {"name": name, "details": []}
            out.append(current)
        elif not line or re.match(r"(panel|witnesses)\b", line, re.I):
            current = None
        elif current is not None and len(current["details"]) < 4:
            current["details"].append(line)
    return [DocumentWitness(name=w["name"], position=w["details"][0] if w["details"] else "", organization=", ".join(w["details"][1:])) for w in out]


def document_witnesses(text):
    return [person.source_dict() for person in parse_document_witnesses(text)]


def parse_pdf_observation(data: bytes) -> PdfWitnessObservation:
    if not data.startswith(b"%PDF"):
        raise ValueError("Witness list response is not a PDF")
    pages = [PdfTextPage(number=i, text=page.extract_text() or '') for i, page in enumerate(PdfReader(io.BytesIO(data)).pages, 1)]
    text = "\n".join(page.text for page in pages)
    sha = hashlib.sha256(data).hexdigest()
    result = {"people": parse_document_witnesses(text), "text_present": bool(text.strip()), "source_text": text,
              "raw_sha256": sha, "parser_version": PARSER_VERSION, "pages": pages,
              "content": RawContent.from_bytes(data, 'application/pdf')}
    if reviewed := REVIEWED.get(sha):
        result["people"] = reviewed["people"]
        result["reviewed_reading"] = {key: value for key, value in reviewed.items() if key != "people"}
        result["reviewed_reading"].update(basis="visual reading of rendered official PDF", reviewed_on="2026-09-28")
    return PdfWitnessObservation.model_validate(result)


def pdf_observation(data):
    return parse_pdf_observation(data).source_dict()


def read_pdf(data):
    result = pdf_observation(data)
    return result["people"], result["text_present"]


def parse_mods_observation(data: bytes) -> ModsWitnessObservation:
    document = parse_mods_document(data)
    return ModsWitnessObservation(people=mods_witnesses(document), raw_sha256=hashlib.sha256(data).hexdigest(),
                                  parser_version=PARSER_VERSION, source_witnesses=document.witnesses,
                                  content=RawContent.from_bytes(data, 'application/xml'))


def mods_observation(data):
    return parse_mods_observation(data).source_dict()


def timestamp():
    return dt.datetime.now(dt.UTC).isoformat()


def get_witnesses(key, url, state, version, day, today, offline, seed_cache=None, package=False):
    saved = state.get(key)
    complete = saved is not None and "people" in saved
    if complete:
        if offline:
            return saved["people"]
        failed = (saved.get("last_check") or {}).get("outcome") == "error"
        # A missing file can appear without a package revision. Retry negatives
        # weekly, and failed refreshes next run, even for an unchanged print.
        unchanged_print = package and saved.get("version") == version and not saved.get("absent")
        if not failed and unchanged_print:
            return saved["people"]
        if not failed and saved.get("version") == version:
            expired = ((today - dt.date.fromisoformat(saved["checked"])).days >= 7
                       if saved.get("absent") else due(saved, day, version, today))
            if not expired:
                return saved["people"]
    data = None
    if not complete and seed_cache:
        path = seed_cache / "mods" / f"{key}.xml" if package else seed_cache / "witness_lists" / re.sub(r"\W+", "_", url.split("/meeting/")[-1])
        if path.exists():
            data = path.read_bytes()
    imported = data is not None
    if not imported and offline:
        raise RuntimeError(f"Missing saved witness source: {key}")
    check = {"mode": "cache_import" if imported else "live", "url": url, "started_at": timestamp()}
    try:
        if not imported:
            response = http.get_with_retry(None, url, allowed=(200, 404))
            check.update(completed_at=timestamp(), status_code=response.status_code)
            data = response.content if response.status_code == 200 else None
        evidence = (mods_observation(data) if package else pdf_observation(data)) if data is not None else {}
    except (ValueError, RuntimeError, OSError, ParseError, PyPdfError) as error:
        check.update(completed_at=timestamp(), outcome="error", error=str(error))
        if data is not None:
            check['content'] = RawContent.from_bytes(data, 'application/xml' if package else 'application/pdf').source_dict()
        state[key] = {**(saved or {}), "url": url, "last_check": check}
        raise
    check.update(completed_at=check.get("completed_at") or timestamp(), outcome="present" if data is not None else "not_found")
    people = evidence.get("people", [])
    state[key] = {"people": people, "url": url, "version": version, "checked": today.isoformat(), "absent": data is None,
                  "text_present": evidence.get("text_present", False), **evidence, "last_check": check, "observation_check": check}
    if imported:
        state[key]["imported_at"] = check["completed_at"]
    elif data is not None:
        state[key]["retrieved_at"] = check["completed_at"]
    return people

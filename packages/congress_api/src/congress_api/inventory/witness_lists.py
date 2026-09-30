"""Parse retained MODS and witness-list PDF bytes without acquisition.

Keep original MODS/PDF bytes beside typed names, source text, URL, version and
check date, including valid empty lists. MODS uses GPO's parser, and PDFs use pypdf reading order.
The research used pdftotext; fixtures and the full seeded comparison check the
change in text extraction. Bad responses are failures, not scanned lists.
"""
import io
import hashlib
import re

from pypdf import PdfReader

from congress_api.gpo.fetch import GOVINFO_CONTENT, mods_witnesses
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



def get_witnesses(key, url, state, version, day, today, offline, seed_cache=None, package=False, *, get=None):
    """Compatibility entry point; acquisition owns fetching and retention."""
    from congress_api.inventory import acquisition
    return acquisition.get_witnesses(key, url, state, version, day, today, offline,
                                     seed_cache, package, **({"get": get} if get is not None else {}))

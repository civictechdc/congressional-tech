"""Fill missing witnesses from MODS and attached witness-list PDFs.

Keep parsed names, URL, version and check date, including valid empty lists;
never keep raw MODS/PDF. MODS uses GPO's parser, and PDFs use pypdf reading order.
The research used pdftotext; fixtures and the full seeded comparison check the
change in text extraction. Bad responses are failures, not scanned lists.
"""
import io
import re

from pypdf import PdfReader

from congress_api import http
from congress_api.gpo.fetch import GOVINFO_CONTENT, mods_witnesses
from congress_api.inventory.common import due
from congress_api.witnesses import TITLE, is_name


def document_witnesses(text):
    out, current = [], None
    for line in (line.strip() for line in text.splitlines()):
        title = TITLE.match(line + " ")
        name = re.sub(r",.*$", "", line[title.end():]).strip() if title else ""
        if is_name(name) and len(line.split()) <= 8 and not line.endswith(":"):
            current = {"name": name, "details": []}
            out.append(current)
        elif not line or re.match(r"(panel|witnesses)\b", line, re.I):
            current = None
        elif current is not None and len(current["details"]) < 4:
            current["details"].append(line)
    return [{"name": w["name"], "position": w["details"][0] if w["details"] else "", "organization": ", ".join(w["details"][1:])} for w in out]


def read_pdf(data):
    if not data.startswith(b"%PDF"):
        raise ValueError("Witness list response is not a PDF")
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return document_witnesses(text), bool(text.strip())


def get_witnesses(key, url, state, version, day, today, offline, seed_cache=None, package=False):
    saved = state.get(key)
    ## GPO's last_modified is authoritative; unchanged prints need no age-based refetch.
    if saved and (offline or (package and saved["version"] == version) or not due(saved, day, version, today)):
        return saved["people"]
    data = None
    if not saved and seed_cache:
        path = seed_cache / "mods" / f"{key}.xml" if package else seed_cache / "witness_lists" / re.sub(r"\W+", "_", url.split("/meeting/")[-1])
        if path.exists():
            data = path.read_bytes()
    if data is None:
        if offline:
            raise RuntimeError(f"Missing saved witness source: {key}")
        response = http.get_with_retry(None, url, allowed=(200, 404))
        data = response.content if response.status_code == 200 else None
    people, text_present = [], False
    if data is not None:
        if package:
            people = mods_witnesses(data)
        else:
            people, text_present = read_pdf(data)
    state[key] = {"people": people, "url": url, "version": version, "checked": today.isoformat(), "absent": data is None, "text_present": text_present}
    return people

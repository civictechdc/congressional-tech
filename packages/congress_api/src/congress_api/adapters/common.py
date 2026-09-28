"""Small adapter values. Identity persistence belongs to the calling application."""
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Callable, Mapping
from urllib.parse import urlsplit

from committee_meeting.common import Identifier, Ref, ReportedTime
from committee_meeting.provenance import Citation, Method, Provenance, SourceRecord
from committee_meeting.materials import DocumentDetails, Material, MaterialVersion, Representation, MaterialLocation, MaterialLink


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def ref(record):
    return Ref(kind=record.kind, id=record.id)


def witness_roles(position):
    """Preserve an explicitly listed nominee role alongside witness participation."""
    return ("witness", "nominee") if re.match(r"^\s*nominee\b", position or "", re.I) else ("witness",)


def web_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme in ("http", "https") and parsed.netloc else None


def reported_time(value):
    if value is None or value == "":
        return None
    value = str(value)
    if len(value) == 10:
        return ReportedTime(date=date.fromisoformat(value), original=value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    zone = "UTC" if value.endswith("Z") else str(parsed.tzinfo) if parsed.tzinfo else None
    return ReportedTime(date=parsed.date(), time=parsed.time().replace(tzinfo=None), timezone=zone,
                        precision="second" if len(value.split("T")[-1].split("+")[0]) >= 8 else "minute", original=value)


def observed_time(raw, now):
    """Use an explicit, zoned source acquisition time; never infer freshness."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed <= now else None
    except (AttributeError, TypeError, ValueError):
        return None


@dataclass
class AdapterContext:
    now: datetime
    input_id: str
    provider: str
    ids: Callable[[str, str], str]
    # Exact, unambiguous publisher files already imported by the application.
    known_materials: Mapping[str, tuple[Material, MaterialVersion]] | None = None

    def source(self, native_key, payload, url=None):
        key = f"{self.provider}|{self.input_id}|{native_key}|{digest(payload)}"
        return SourceRecord(id=self.ids("source_record", key), provider=self.provider,
                            identifier=Identifier(scheme=f"{self.provider}:record", value=str(native_key)),
                            input_snapshot_id=self.input_id, imported_at=self.now,
                            url=web_url(url), payload=payload)

    def evidence(self, source, basis="reported", method=None, selector=None):
        if isinstance(method, str):
            method = Method(name=method, version="1")
        return Provenance(citations=(Citation(source=ref(source), selector_type="json_pointer" if selector is not None else None,
                                               selector=selector),), basis=basis, method=method)


def material_records(context, evidence, key, *, title=None, urls=(), details=None, subject=None, role="supporting", identifiers=()):
    """Keep source identities unless an exact publisher file has a known identity."""
    urls = tuple(dict.fromkeys(urls))
    known = (getattr(context, 'known_materials', None) or {}).get(urls[0]) if len(urls) == 1 else None
    if known and (details is None or details.type == 'document'):
        material, version = known
        # A link label is not a competing official document title or edition.
        # Keep the publisher fields and both observations; the label stays in
        # the source payload addressed by this additional citation.
        def cited(record):
            citations = {c.model_dump_json(): c for c in (*record.provenance.citations, *evidence.citations)}
            return record.model_copy(update={'provenance': record.provenance.model_copy(
                update={'citations': tuple(citations.values())})})
        out = [cited(material), cited(version)]
        if subject is not None:
            out.append(MaterialLink(id=context.ids('material_link', key + '|' + subject.kind + '|' + subject.id + '|' + role),
                material=ref(material), version=ref(version), subject=subject, role=role, provenance=evidence))
        return out
    material = Material(id=context.ids("material", key), title=title or None,
                        details=details or DocumentDetails(category="unknown"), identifiers=identifiers, provenance=evidence)
    version = MaterialVersion(id=context.ids("material_version", key + "|reported-edition"), material=ref(material),
                              provenance=evidence)
    out = [material, version]
    for url in dict.fromkeys(urls):
        if not web_url(url):
            continue
        suffix = urlsplit(url).path.rsplit(".", 1)[-1].lower()
        media = {"pdf": "application/pdf", "xml": "application/xml", "html": "text/html", "htm": "text/html", "csv": "text/csv", "txt": "text/plain", "vtt": "text/vtt", "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "rtf": "application/rtf"}.get(suffix)
        out.append(Representation(id=context.ids("representation", key + "|" + url), version=ref(version),
                                  locations=(MaterialLocation(url=url, role="player" if details and details.type == "recording" else "download"),),
                                  media_type=media, format_label=suffix if media else None, provenance=evidence))
    if subject is not None:
        out.append(MaterialLink(id=context.ids("material_link", key + "|" + subject.kind + "|" + subject.id + "|" + role),
                                material=ref(material), version=ref(version), subject=subject, role=role, provenance=evidence))
    return out

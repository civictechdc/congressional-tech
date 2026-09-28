"""Small adapter values. Identity persistence belongs to the calling application."""
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Callable
from urllib.parse import urlsplit

from committee_meeting.common import Identifier, Ref, ReportedTime
from committee_meeting.provenance import Citation, Method, Provenance, SourceRecord
from committee_meeting.materials import DocumentDetails, Material, MaterialVersion, Representation, MaterialLocation, MaterialLink


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def ref(record):
    return Ref(kind=record.kind, id=record.id)


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


@dataclass
class AdapterContext:
    now: datetime
    input_id: str
    provider: str
    ids: Callable[[str, str], str]

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
    """One source-described material; identity across independent listings is not inferred."""
    material = Material(id=context.ids("material", key), title=title or None,
                        details=details or DocumentDetails(category="unknown"), identifiers=identifiers, provenance=evidence)
    version = MaterialVersion(id=context.ids("material_version", key + "|reported-edition"), material=ref(material),
                              provenance=evidence)
    out = [material, version]
    for url in dict.fromkeys(urls):
        if not web_url(url):
            continue
        suffix = urlsplit(url).path.rsplit(".", 1)[-1].lower()
        media = {"pdf": "application/pdf", "xml": "application/xml", "html": "text/html", "txt": "text/plain", "vtt": "text/vtt"}.get(suffix)
        out.append(Representation(id=context.ids("representation", key + "|" + url), version=ref(version),
                                  locations=(MaterialLocation(url=url, role="player" if details and details.type == "recording" else "download"),),
                                  media_type=media, format_label=suffix if media else None, provenance=evidence))
    if subject is not None:
        out.append(MaterialLink(id=context.ids("material_link", key + "|" + subject.kind + "|" + subject.id + "|" + role),
                                material=ref(material), version=ref(version), subject=subject, role=role, provenance=evidence))
    return out

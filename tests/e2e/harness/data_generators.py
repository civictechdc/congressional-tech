"""Synthetic Data Generators for Boundary, Stress, and Corner Case Verification.

Generates precise payloads, Unicode replacement strings, PDF byte patterns,
and multi-congress relational structures.
"""

from __future__ import annotations
import hashlib
import json
import uuid
from typing import Any

from .contracts import MAX_CELL_SIZE, PDF_MAGIC


class SyntheticDataGenerator:
    """Factory for synthetic test cases and boundary conditions."""

    @staticmethod
    def generate_pdf_bytes(length: int = 1024, version: str = "1.5") -> bytes:
        """Generate valid synthetic PDF binary bytes beginning with %PDF- header."""
        header = f"%PDF-{version}\n%\xe2\xe3\xcf\xd3\n".encode("latin1")
        body = b"stream\nBT /F1 12 Tf (Test Document) Tj ET\nendstream\n"
        trailer = b"%%EOF\n"
        padding_needed = max(0, length - len(header) - len(body) - len(trailer))
        padding = b"x" * padding_needed
        return header + body + padding + trailer

    @staticmethod
    def generate_high_ufffd_text(length: int = 1000, replacement_ratio: float = 0.10) -> str:
        """Generate text with exact ratio of Unicode replacement characters (U+FFFD)."""
        ufffd_count = int(length * replacement_ratio)
        ascii_count = length - ufffd_count
        chars = ["\ufffd"] * ufffd_count + ["A"] * ascii_count
        # Deterministic shuffle / interleaving
        interleaved: list[str] = []
        step = max(1, length // max(1, ufffd_count))
        u_idx = 0
        a_idx = 0
        for i in range(length):
            if i % step == 0 and u_idx < ufffd_count:
                interleaved.append(chars[u_idx])
                u_idx += 1
            elif a_idx < ascii_count:
                interleaved.append(chars[ufffd_count + a_idx])
                a_idx += 1
            else:
                interleaved.append("\ufffd")
        return "".join(interleaved[:length])

    @staticmethod
    def generate_string_of_bytes(target_bytes: int, char: str = "A") -> str:
        """Generate string with exact encoded UTF-8 byte length."""
        char_bytes = char.encode("utf-8")
        repeat_count = target_bytes // len(char_bytes)
        remainder = target_bytes % len(char_bytes)
        return (char * repeat_count) + ("." * remainder)

    @staticmethod
    def generate_source_record(
        provider: str = "congress.gov",
        scheme: str = "bill",
        value: str = "hr1234",
        scope: str = "118",
        title: str = "Test Hearing Record",
        payload_dict: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate standard SourceRecord test dictionary."""
        payload = payload_dict if payload_dict is not None else {
            "title": title,
            "summary": "Sample hearing summary text",
            "url": f"https://example.com/{scheme}/{value}",
        }
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(payload_bytes).hexdigest()
        rec_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{provider}:{scheme}:{value}:{digest}"))

        return {
            "id": rec_id,
            "kind": "source_record",
            "provider": provider,
            "url": f"https://example.com/{scheme}/{value}",
            "title": title,
            "retrieved_at": "2026-10-22T12:00:00Z",
            "source_modified_at": "2026-10-20T10:00:00Z",
            "imported_at": "2026-10-22T13:00:00Z",
            "identifier_scheme": scheme,
            "identifier_value": value,
            "identifier_scope": scope,
            "facts": [{"label": "Category", "value": "Hearing"}],
            "links": [{"group": "Primary", "label": "Web Page", "href": f"https://example.com/{value}"}],
            "retained_uri": f"bodies/sha256/{digest[:2]}/{digest}.gz",
            "retained_sha256": digest,
            "raw_payload_bytes": payload_bytes,
        }

    @staticmethod
    def generate_youtube_video_record(
        video_id: str = "abc123XYZ",
        title: str = "Committee Hearing Live Stream",
        published_at: str = "2026-10-20T14:30:00Z",
        system_code: str = "hsed00",
        camel_case: bool = True,
    ) -> dict[str, Any]:
        """Generate YouTube video dictionary in camelCase (real API) or snake_case."""
        if camel_case:
            return {
                "systemCode": system_code,
                "videoId": video_id,
                "publishedAt": published_at,
                "videoPublishedAt": published_at,
                "title": title,
                "upstream": {
                    "snippet": {
                        "title": title,
                        "description": "Full hearing description text",
                    }
                },
            }
        else:
            return {
                "system_code": system_code,
                "video_id": video_id,
                "published_at": published_at,
                "title": title,
                "payload_json": json.dumps({"title": title}),
            }

    @staticmethod
    def generate_committee_record(
        system_code: str = "hsed00",
        congress: int = 118,
        chamber: str = "House",
        nested: bool = True,
    ) -> dict[str, Any]:
        """Generate committee record in nested CommitteeSnapshot format or flat."""
        detail = {
            "name": "Committee on Education and the Workforce",
            "jurisdiction": "Education and labor laws",
            "history": "Established in 1867",
        }
        if nested:
            return {
                "congress": congress,
                "_url": f"https://api.congress.gov/v3/committee/{congress}",
                "committee": {
                    "systemCode": system_code,
                    "chamber": chamber,
                    "updateDate": "2026-10-21T09:00:00Z",
                    "detail": detail,
                },
            }
        else:
            return {
                "systemCode": system_code,
                "congress": congress,
                "chamber": chamber,
                "updateDate": "2026-10-21T09:00:00Z",
                "detail": detail,
            }

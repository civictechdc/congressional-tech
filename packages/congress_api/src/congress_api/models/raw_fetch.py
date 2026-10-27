"""File-backed transfer facts shared by acquisition and raw retention."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BodyFile:
    path: Path
    sha256: str
    size: int
    media_type: str | None
    sniffed_format: str | None
    sniff_version: str | None
    intact: bool | None
    sniff_error: str | None = None


@dataclass(frozen=True)
class Transfer:
    path: Path
    url: str
    http_status: int | None
    headers: dict
    complete: bool
    error: str | None = None
    provider_status: int | None = None
    sha256: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class FetchAttempt:
    requested_url: str
    url: str
    retrieved_at: str
    transport: str
    http_status: int | None
    provider_status: int | None
    headers: dict
    redirects: tuple
    complete: bool
    body: BodyFile | None
    error: str | None = None


@dataclass(frozen=True)
class FetchResult:
    final: FetchAttempt
    prior_attempts: tuple = ()

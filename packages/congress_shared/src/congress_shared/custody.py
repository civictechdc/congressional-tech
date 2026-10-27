"""Shared file-custody verification, atomic writes, and canonical JSON receipts.

All functions in this module are pure standard-library helpers with no import-time
side effects, safe to import from any package or CLI entrypoint.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
from stat import S_ISREG
import tempfile
from typing import Any, Literal
from weakref import WeakValueDictionary

CHUNK_BYTES = 1024 * 1024


def custody_identity(path: Path | str) -> tuple[int, int, int, int, int, int]:
    """Return ``(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns, st_nlink)`` for a regular file."""
    resolved = Path(path)
    if resolved.is_symlink():
        raise ValueError(f"Custody-verified file cannot be a symlink: {resolved}")
    stat = resolved.stat()
    if not S_ISREG(stat.st_mode):
        raise ValueError(f"Custody-verified file must be a regular file: {resolved}")
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_nlink)


class VerifiedFile(dict):
    """A JSON-compatible digest with process-local, exact-file custody.

    Supports both immutable attribute access (``vf.path``, ``vf.sha256``,
    ``vf.size_bytes``) and mapping access (``vf['sha256']``, ``vf['bytes']``),
    plus process/inode custody verification via ``vf.require(path)``.
    """

    _issued: WeakValueDictionary[int, VerifiedFile] = WeakValueDictionary()

    def __init__(
        self,
        path_or_value: Path | str | Mapping[str, Any],
        sha256_digest: str | None = None,
        size_bytes: int | None = None,
        *,
        pid: int | None = None,
        target: Path | str | None = None,
        identity: tuple[int, int, int, int, int, int] | None = None,
    ) -> None:
        if isinstance(path_or_value, Mapping):
            super().__init__(path_or_value)
            raw_path = target if target is not None else path_or_value.get("path")
            resolved_path = Path(raw_path).resolve() if raw_path is not None else None
            if "path" in self and resolved_path is not None:
                self["path"] = resolved_path
            resolved_sha256 = (
                sha256_digest if sha256_digest is not None else self.get("sha256")
            )
            resolved_size = (
                size_bytes
                if size_bytes is not None
                else self.get("bytes", self.get("size_bytes"))
            )
        else:
            if sha256_digest is None or size_bytes is None:
                raise TypeError(
                    "VerifiedFile(path, sha256, size_bytes) requires sha256 and size_bytes"
                )
            raw_input_path = Path(path_or_value)
            resolved_path = raw_input_path.resolve()
            resolved_sha256 = str(sha256_digest)
            resolved_size = int(size_bytes)
            super().__init__(sha256=resolved_sha256, bytes=resolved_size)
            if pid is None and target is None and identity is None:
                try:
                    if not raw_input_path.is_symlink() and raw_input_path.is_file():
                        pid = os.getpid()
                        target = resolved_path
                        identity = custody_identity(raw_input_path)
                except OSError:
                    pass

        resolved_target = (
            Path(target).resolve()
            if target is not None
            else (resolved_path if resolved_path is not None and pid is not None else None)
        )
        object.__setattr__(self, "path", resolved_path)
        object.__setattr__(self, "sha256", resolved_sha256)
        object.__setattr__(self, "size_bytes", resolved_size)
        object.__setattr__(self, "pid", pid)
        object.__setattr__(self, "process", pid)
        object.__setattr__(self, "target", resolved_target)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "custody", identity)
        object.__setattr__(self, "facts", (self.get("bytes"), self.get("sha256")))
        if pid is not None:
            self._issued[id(self)] = self

    def __getitem__(self, key: str) -> Any:
        if key == "path" and not super().__contains__("path") and self.path is not None:
            return self.path
        if key == "size_bytes" and not super().__contains__("size_bytes") and self.size_bytes is not None:
            return self.size_bytes
        return super().__getitem__(key)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("VerifiedFile attributes are immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("VerifiedFile attributes are immutable")

    def _rebind_custody(self, identity: tuple[int, int, int, int, int, int]) -> None:
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "custody", identity)

    def _require_custody(self, path: Path | str) -> VerifiedFile:
        """Check metadata only; callers must independently verify consumed bytes."""
        if (
            self._issued.get(id(self)) is not self
            or self.process != os.getpid()
            or self.target is None
            or Path(path).resolve() != self.target
            or custody_identity(path) != self.custody
            or (self.get("bytes"), self.get("sha256")) != self.facts
        ):
            raise ValueError(f"Verified catalog file custody changed: {path}")
        return self


    def require(self, path: Path | str) -> VerifiedFile:
        """Verify current bytes as well as process, path and file metadata."""
        self._require_custody(path)
        try:
            current = verify_local_file(path, expected_sha256=self["sha256"],
                expected_size=self["bytes"], sha256_factory=sha256, identity_fn=custody_identity)
        except ValueError as error:
            raise ValueError(f"Verified catalog file custody or bytes changed: {path}") from error
        if current.custody != self.custody:
            raise ValueError(f"Verified catalog file custody changed: {path}")
        return self


def issue_verified_file(path: Path | str, facts: Mapping[str, Any]) -> VerifiedFile:
    """Issue a :class:`VerifiedFile` preserving all metadata keys in ``facts``."""
    resolved = Path(path)
    return VerifiedFile(
        facts,
        pid=os.getpid(),
        target=resolved,
        identity=custody_identity(resolved),
    )


def verify_local_file(
    path: Path | str,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    *,
    sha256_factory: Callable[[], Any] = sha256,
    identity_fn: Callable[[Path | str], tuple[int, int, int, int, int, int]] = custody_identity,
) -> VerifiedFile:
    """Stream-verify a local regular file and return an issued :class:`VerifiedFile`."""
    resolved_path = Path(path)
    before = identity_fn(resolved_path)
    digest = sha256_factory()
    size = 0
    with resolved_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
    after = identity_fn(resolved_path)
    if before != after or resolved_path.stat().st_size != size:
        raise ValueError(f"Catalog changed during hashing: {resolved_path}")
    actual_sha256 = digest.hexdigest()
    if expected_size is not None and size != expected_size:
        raise ValueError(
            f"File size mismatch for {resolved_path}: expected {expected_size}, got {size}"
        )
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ValueError(
            f"File SHA-256 mismatch for {resolved_path}: expected {expected_sha256}, got {actual_sha256}"
        )
    return VerifiedFile(
        resolved_path,
        actual_sha256,
        size,
        pid=os.getpid(),
        target=resolved_path.resolve(),
        identity=after,
    )


def file_identity(path: Path | str) -> VerifiedFile:
    """Alias for :func:`verify_local_file` with no pre-existing expectations."""
    return verify_local_file(path)


def write_atomic_bytes(
    path: Path | str,
    data: bytes | bytearray | memoryview,
    *,
    temp_mode: Literal["unique", "fixed"] = "unique",
    temp_path: Path | str | None = None,
    fsync: bool = True,
    fsync_dir: bool = False,
) -> VerifiedFile:
    """Atomically write ``data`` to ``path`` via a sibling temporary file and ``Path.replace``.

    On any write, flush, fsync, or replace failure, the temporary file is unlinked
    before the exception propagates.
    """
    target = Path(path)
    raw = bytes(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    if temp_path is not None:
        temporary = Path(temp_path)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        fd = None
    elif temp_mode == "fixed":
        temporary = target.with_suffix(target.suffix + ".tmp")
        fd = None
    elif temp_mode == "unique":
        fd, raw_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(raw_name)
    else:
        raise ValueError(f"Unsupported temp_mode: {temp_mode!r}")

    try:
        if fd is not None:
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(raw)
                stream.flush()
                if fsync:
                    os.fsync(stream.fileno())
        else:
            with temporary.open("wb") as stream:
                stream.write(raw)
                stream.flush()
                if fsync:
                    os.fsync(stream.fileno())
        temporary.replace(target)
        if fsync_dir:
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)
        raise

    digest = sha256(raw).hexdigest()
    identity = custody_identity(target)
    return VerifiedFile(
        target,
        digest,
        len(raw),
        pid=os.getpid(),
        target=target.resolve(),
        identity=identity,
    )


def canonical_json_bytes(
    payload: Any,
    *,
    ensure_ascii: bool = False,
    trailing_newline: bool = False,
    allow_nan: bool = True,
    default: Callable[[Any], Any] | None = None,
) -> bytes:
    """Serialize ``payload`` to deterministic canonical JSON UTF-8 bytes."""
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=ensure_ascii,
        allow_nan=allow_nan,
        default=default,
    )
    if trailing_newline:
        text += "\n"
    return text.encode("utf-8")


def write_bound_receipt(
    path: Path | str,
    payload: Any,
    *,
    temp_mode: Literal["unique", "fixed"] = "unique",
    temp_path: Path | str | None = None,
    ensure_ascii: bool = False,
    trailing_newline: bool = True,
    allow_nan: bool = True,
    default: Callable[[Any], Any] | None = None,
    fsync: bool = True,
    fsync_dir: bool = False,
) -> VerifiedFile:
    """Atomically write ``payload`` as canonical JSON and return its :class:`VerifiedFile`."""
    return write_atomic_json(
        path,
        payload,
        temp_mode=temp_mode,
        temp_path=temp_path,
        ensure_ascii=ensure_ascii,
        trailing_newline=trailing_newline,
        allow_nan=allow_nan,
        default=default,
        fsync=fsync,
        fsync_dir=fsync_dir,
    )


def write_atomic_json(
    path: Path | str,
    payload: Any,
    *,
    temp_mode: Literal["unique", "fixed"] = "unique",
    temp_path: Path | str | None = None,
    ensure_ascii: bool = False,
    trailing_newline: bool = True,
    allow_nan: bool = True,
    default: Callable[[Any], Any] | None = None,
    fsync: bool = True,
    fsync_dir: bool = False,
) -> VerifiedFile:
    """Serialize ``payload`` via :func:`canonical_json_bytes` and write atomically."""
    raw = canonical_json_bytes(
        payload,
        ensure_ascii=ensure_ascii,
        trailing_newline=trailing_newline,
        allow_nan=allow_nan,
        default=default,
    )
    return write_atomic_bytes(
        path,
        raw,
        temp_mode=temp_mode,
        temp_path=temp_path,
        fsync=fsync,
        fsync_dir=fsync_dir,
    )


def read_bound_receipt(
    path: Path | str,
    *,
    expected_fields: Mapping[str, Any] | None = None,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> dict[str, Any]:
    """Read and parse a JSON receipt written by :func:`write_bound_receipt`, verifying bindings."""
    verified = verify_local_file(
        path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
    )
    raw = verified.path.read_bytes()
    if len(raw) != verified.size_bytes or sha256(raw).hexdigest() != verified.sha256:
        raise ValueError(f"Receipt changed during read: {path}")
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"Bound receipt must be a JSON object: {path}")
    if expected_fields is not None:
        for key, expected_value in expected_fields.items():
            if parsed.get(key) != expected_value:
                raise ValueError(
                    f"Bound receipt field mismatch for {key!r} in {path}: "
                    f"expected {expected_value!r}, got {parsed.get(key)!r}"
                )
    return parsed


def copy_checked(
    src: Path | str,
    dst: Path | str,
    *,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
    chunk_size: int = CHUNK_BYTES,
    temp_mode: Literal["unique", "fixed"] = "unique",
    temp_path: Path | str | None = None,
    fsync: bool = True,
    fsync_dir: bool = False,
) -> VerifiedFile:
    """Stream-copy ``src`` to ``dst`` and verify custody in a single pass."""
    resolved_src = Path(src)
    target = Path(dst)
    before_src = custody_identity(resolved_src)

    target.parent.mkdir(parents=True, exist_ok=True)
    if temp_path is not None:
        temporary = Path(temp_path)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        fd = None
    elif temp_mode == "fixed":
        temporary = target.with_suffix(target.suffix + ".tmp")
        fd = None
    elif temp_mode == "unique":
        fd, raw_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(raw_name)
    else:
        raise ValueError(f"Unsupported temp_mode: {temp_mode!r}")

    digest = sha256()
    size = 0
    try:
        if fd is not None:
            out_file = os.fdopen(fd, "wb")
            fd = None
        else:
            out_file = temporary.open("wb")

        with out_file as out_stream, resolved_src.open("rb") as in_stream:
            for chunk in iter(lambda: in_stream.read(chunk_size), b""):
                size += len(chunk)
                digest.update(chunk)
                out_stream.write(chunk)
            out_stream.flush()
            if fsync:
                os.fsync(out_stream.fileno())

        after_src = custody_identity(resolved_src)
        if before_src != after_src or resolved_src.stat().st_size != size:
            raise ValueError(f"Source file changed during checked copy: {src}")

        actual_sha256 = digest.hexdigest()
        if expected_bytes is not None and size != expected_bytes:
            raise ValueError(
                f"File size mismatch for {src}: expected {expected_bytes}, got {size}"
            )
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise ValueError(
                f"SHA-256 mismatch for {src}: expected {expected_sha256}, got {actual_sha256}"
            )

        temporary.replace(target)
        if fsync_dir:
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)
        raise

    return VerifiedFile(
        target,
        actual_sha256,
        size,
        pid=os.getpid(),
        target=target.resolve(),
        identity=custody_identity(target),
    )


def iter_canonical_digest(
    items: Any,
    *,
    ensure_ascii: bool = False,
    allow_nan: bool = True,
    default: Callable[[Any], Any] | None = None,
) -> str:
    """Incrementally hash an iterable of JSON-serializable items into a SHA-256 hex digest."""
    digest = sha256()
    for item in items:
        if isinstance(item, (bytes, bytearray, memoryview)):
            raw = bytes(item)
            if not raw.endswith(b"\n"):
                raw += b"\n"
            digest.update(raw)
        else:
            digest.update(
                canonical_json_bytes(
                    item,
                    ensure_ascii=ensure_ascii,
                    trailing_newline=True,
                    allow_nan=allow_nan,
                    default=default,
                )
            )
    return digest.hexdigest()


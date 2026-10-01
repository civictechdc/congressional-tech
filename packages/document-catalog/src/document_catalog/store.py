"""Content-addressed evidence, append-only attempts and disposable cache pointers."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile
import time
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(value):
    return digest(canonical(value))


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def versions():
    packages = {}
    for name in ["PyMuPDF", "Pillow", "numpy", "docling", "docling-ibm-models", "torch", "transformers", "pyobjc-framework-Vision"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"packages": packages, "python": platform.python_version(), "system": platform.platform(),
            "implementation_sha256": identity({p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))})}


@contextmanager
def catalog_lock(root):
    """One writer owns a catalog; failed/killed processes release the OS lock."""
    import fcntl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".writer.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another process owns this catalog") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class IntegrityError(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise IntegrityError("Evidence path escapes catalog")
        return path

    def put(self, data, suffix="bin"):
        sha = digest(data)
        relative = f"objects/{sha[:2]}/{sha}.{suffix}"
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link publication never exposes partial bytes and never
                # replaces an already published immutable object.
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise IntegrityError(f"Immutable object changed: {relative}")
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {"path": relative, "sha256": sha, "bytes": len(data)}

    def put_json(self, value):
        return self.put(canonical(value), "json")

    def read(self, ref):
        data = self.path(ref["path"]).read_bytes()
        if digest(data) != ref["sha256"] or len(data) != ref["bytes"]:
            raise IntegrityError(f"Evidence digest mismatch: {ref['path']}")
        return data

    def json(self, ref):
        return json.loads(self.read(ref))

    def verify_refs(self, value, _seen=None):
        if _seen is None:
            _seen = set()
        if isinstance(value, dict):
            if set(value) == {"path", "sha256", "bytes"}:
                key = (value["path"], value["sha256"], value["bytes"])
                if key not in _seen:
                    self.read(value)
                    _seen.add(key)
            for child in value.values():
                self.verify_refs(child, _seen)
        elif isinstance(value, list):
            for child in value:
                self.verify_refs(child, _seen)

    def stage(self, name, inputs, config, environment, produce, retry_failed=False):
        key_data = {"stage": name, "inputs": inputs, "config": config, "environment": environment}
        key = identity(key_data)
        pointer = self.root / "cache" / name / f"{key}.json"
        previous = None
        if pointer.exists():
            previous = json.loads(pointer.read_text())
            receipt = self.json(previous)
            if receipt["key"] != key or receipt["identity"] != key_data:
                raise IntegrityError("Cache points to incompatible attempt")
            self.verify_refs(receipt)
            if receipt["status"] == "success" or not retry_failed:
                return receipt, previous, True
        started = time.monotonic()
        try:
            data = produce()
            self.verify_refs(data)
            status, error = data.get("stage_status", "success"), None
        except IntegrityError:
            raise
        except Exception as exc:
            data, status, error = None, "failed", f"{type(exc).__name__}: {exc}"
        receipt = {"version": 1, "attempt_id": uuid.uuid4().hex, "key": key, "identity": key_data,
                   "created_at": now(), "seconds": time.monotonic() - started,
                   "status": status, "error": error, "data": data, "previous_attempt": previous}
        ref = self.put_json(receipt)
        atomic_json(pointer, ref)
        return receipt, ref, False

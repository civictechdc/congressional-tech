"""Resolution for the native docspec binary across local and CI environments."""
import os
from pathlib import Path


def resolve_docspec_binary(binary: Path | str | None = None) -> Path:
    """Resolve the native docspec binary without hardcoded machine paths."""
    if binary is not None:
        p = Path(binary).resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"Specified docspec binary does not exist: {binary}")

    for env_var in ("DOCSPEC_BINARY", "DOCSPEC_BIN"):
        env_bin = os.environ.get(env_var)
        if env_bin and Path(env_bin).is_file():
            return Path(env_bin).resolve()

    # Search candidate directories relative to package location and cwd
    search_roots = []
    pkg_dir = Path(__file__).resolve().parent
    for parent in (pkg_dir, *pkg_dir.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            search_roots.extend([parent, parent.parent])
            break
    cwd = Path.cwd()
    search_roots.extend([cwd, cwd.parent])

    for root in search_roots:
        candidates = (
            root / "spicy-stack" / "docspec-rs" / "target" / "release" / "docspec",
            root / "spicy-stack" / "docspec-rs" / "target" / "debug" / "docspec",
            root / "docspec-rs" / "target" / "release" / "docspec",
            root / "docspec-rs" / "target" / "debug" / "docspec",
            root / "target" / "release" / "docspec",
            root / "target" / "debug" / "docspec",
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.resolve()

    raise FileNotFoundError("Unable to locate native docspec binary")

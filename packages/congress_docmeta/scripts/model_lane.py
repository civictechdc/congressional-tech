#!/usr/bin/env python3
"""Run the `docmeta-model` lane: DocMeta tests that need Apple Silicon engines (`fast-gemma4`, `fast-decision-models`, etc.).

Apple Silicon engines are not in `congressional-tech/uv.lock`. This lane prefers the unified
`../fast-silicon/.venv/bin/python` workspace interpreter (`FAST_SILICON_PYTHON`), falling back to
`FAST_GEMMA4_PYTHON` / `../fast-gemma4/.venv/bin/python`, with this checkout's `congress_docmeta`
first on `PYTHONPATH`. It fails loudly if required R8 postal-address / JSON Schema dependencies
(`usaddress`, `pycountry`, `msgspec_schemaorg`, `msgspec`, `jsonschema`) are missing.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
TESTS = PACKAGE / "tests/model"

REQUIRED_R8_IMPORTS: tuple[tuple[str, str], ...] = (
    ("usaddress", "usaddress==0.5.14"),
    ("pycountry", "pycountry==26.2.16"),
    ("msgspec_schemaorg", "msgspec-schemaorg==0.2.1"),
    ("msgspec", "msgspec==0.21.1"),
    ("jsonschema", "jsonschema>=4.18,<5"),
)

_SIBLING_ARTIFACT_ENVS: tuple[tuple[str, str], ...] = (
    ("fast-gemma4", "FAST_GEMMA4_HOME"),
    ("fast-decision-models", "FAST_DECISION_MODELS_HOME"),
    ("fast-bge-small", "FAST_BGE_SMALL_HOME"),
    ("fast-embeddinggemma-2", "FAST_EMBEDDINGGEMMA2_HOME"),
    ("fast-gpt-oss", "FAST_GPT_OSS_HOME"),
)


def sibling_work_root() -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(common).parent.parent  # a worktree's main checkout, then its sibling parent dir


def engine_python() -> Path:
    if named := os.environ.get("FAST_SILICON_PYTHON"):
        return Path(named).expanduser()
    if named := os.environ.get("FAST_GEMMA4_PYTHON"):
        return Path(named).expanduser()
    work_root = sibling_work_root()
    fast_silicon_py = work_root / "fast-silicon/.venv/bin/python"
    if fast_silicon_py.is_file():
        return fast_silicon_py
    return work_root / "fast-gemma4/.venv/bin/python"


def decision_models_src() -> Path:
    if named := os.environ.get("FAST_DECISION_MODELS_SRC"):
        return Path(named).expanduser()
    return sibling_work_root() / "fast-decision-models/src"


def _apply_sibling_artifact_home_defaults(env: dict[str, str], work_root: Path) -> None:
    """Point `FAST_*_HOME` at sibling repos carrying staged `artifacts/` if monorepo `packages/*` lacks them."""
    mono_pkgs = work_root / "fast-silicon" / "packages"
    for pkg_name, env_var in _SIBLING_ARTIFACT_ENVS:
        if env.get(env_var):
            continue
        mono_art = mono_pkgs / pkg_name / "artifacts"
        sib_dir = work_root / pkg_name
        sib_art = sib_dir / "artifacts"
        mono_has = mono_art.is_dir() and any(mono_art.iterdir())
        sib_has = sib_art.is_dir() and any(sib_art.iterdir())
        if not mono_has and sib_has:
            env[env_var] = str(sib_dir)


def main() -> int:
    if sys.argv[1:2] != ["test"]:
        raise SystemExit("Usage: .venv/bin/python scripts/dev.py test docmeta-model [-- pytest arguments]")
    python = engine_python()
    if not python.is_file():
        raise SystemExit(
            f"No Apple Silicon engine interpreter at {python}; set FAST_SILICON_PYTHON (preferred) or "
            "FAST_GEMMA4_PYTHON. This lane runs only where the engines are installed (Apple Silicon)."
        )

    work_root = sibling_work_root()
    # This checkout's package first, then sibling fast-decision-models if not already in the venv, then caller PYTHONPATH.
    path_parts = [str(PACKAGE / "src")]
    fdm_src = decision_models_src()
    is_fast_silicon_venv = "fast-silicon" in python.parts
    if not is_fast_silicon_venv and fdm_src.is_dir():
        path_parts.append(str(fdm_src))
    if extra := os.environ.get("PYTHONPATH"):
        path_parts.append(extra)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(path_parts), PYTHONDONTWRITEBYTECODE="1")
    _apply_sibling_artifact_home_defaults(env, work_root)

    r8_check_list = repr(REQUIRED_R8_IMPORTS)
    probe_code = (
        "import importlib, json, sys\n"
        "import congress_docmeta, fast_gemma4, fast_decision_models\n"
        f"missing = []\n"
        f"for mod_name, spec in {r8_check_list}:\n"
        "    try:\n"
        "        importlib.import_module(mod_name)\n"
        "    except Exception:\n"
        "        missing.append(spec)\n"
        "print(json.dumps({'docmeta_file': congress_docmeta.__file__, 'missing_r8': missing}))\n"
    )
    probe = subprocess.run([str(python), "-c", probe_code], capture_output=True, text=True, env=env)
    if probe.returncode:
        raise SystemExit(
            f"{python} cannot import congress_docmeta + Apple Silicon engines: "
            f"{probe.stderr.strip() or probe.stdout.strip()}"
        )
    import json

    info = json.loads(probe.stdout.strip().splitlines()[-1])
    if not Path(info["docmeta_file"]).resolve().is_relative_to((PACKAGE / "src").resolve()):
        raise SystemExit(f"{python} resolved congress_docmeta outside this checkout: {info['docmeta_file']}")
    if info["missing_r8"]:
        missing_str = ", ".join(info["missing_r8"])
        raise SystemExit(
            f"{python} is missing required R8 postal-address / schema dependencies: {missing_str}.\n"
            "Without them rule R8 cannot extract `work_addr` or validate strict V4 schemas.\n"
            "Fix: run `cd ../fast-silicon && uv sync --extra dev --extra extract` and use FAST_SILICON_PYTHON "
            "(or install those packages into the selected interpreter)."
        )

    return subprocess.call(
        [
            str(python),
            "-m",
            "pytest",
            "-c",
            str(TESTS / "pytest.ini"),
            "--rootdir",
            str(TESTS),
            *(sys.argv[2:] or [str(TESTS)]),
        ],
        cwd=REPO,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())

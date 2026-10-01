"""Command-line interface; ``--help`` and JSON examples are the usage guide."""

import argparse
import json
from pathlib import Path
import sys

from .config import DEFAULT, load_config
from .pipeline import import_plans, load_catalog, review, run
from .store import atomic_json, catalog_lock


def parser():
    result = argparse.ArgumentParser(description="Build evidence-preserving local document catalogs. PDFs have page geometry; other formats remain explicit unsupported records. No field extraction or remote models run. Exit codes: 0 processed/valid, 1 command or validation error, 2 published partial catalog.")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-config", help="Write a version-1 category configuration; edit roles, prompt anchors and schema references")
    init.add_argument("--output", required=True)
    build = commands.add_parser("run", help="Discover sources, capture pages, run configured local OCR/layout, group candidates and export structural plans")
    build.add_argument("--input", action="append", default=[], help="File or recursive directory; repeatable")
    build.add_argument("--manifest", help="JSON sources/documents array; relative paths resolve against manifest directory; gzip source bodies are decoded")
    build.add_argument("--output", required=True, help="Catalog directory, outside input directories")
    build.add_argument("--config")
    build.add_argument("--workers", type=int, default=2)
    build.add_argument("--retry-failed", action="store_true", help="Append new attempts for failed/partial stages; retain all prior evidence")
    for name, description in [("import-plans", "Validate a whole batch of model/manual semantic section plans, then append immutable provenance"),
                              ("review", "Validate and append human/agent judgments without replacing automatic states")]:
        command = commands.add_parser(name, help=description)
        command.add_argument("--catalog", required=True)
        command.add_argument("--batch", required=True)
    for name, description in [("validate", "Check source/evidence/export digests, page accounting, geometry and section consistency"),
                              ("export", "Verify and report immutable JSON/Parquet/HTML exports for the current catalog"),
                              ("status", "Show processing, semantic-unknown and review counts separately")]:
        command = commands.add_parser(name, help=description)
        command.add_argument("--catalog", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init-config":
            if Path(args.output).exists():
                raise ValueError("Refusing to overwrite an existing configuration")
            atomic_json(args.output, DEFAULT)
            output = {"config": str(Path(args.output).resolve())}
        elif args.command == "run":
            if not args.input and not args.manifest:
                raise ValueError("run requires --input or --manifest")
            output = run(args.input, args.output, load_config(args.config), args.manifest, args.workers, args.retry_failed)
            _, catalog, _ = load_catalog(args.output)
            output["summary"] = catalog["summary"]
            print(json.dumps(output, indent=2))
            return 2 if catalog["summary"]["status"] == "partial" else 0
        elif args.command == "import-plans":
            output = import_plans(args.catalog, args.batch)
        elif args.command == "review":
            output = review(args.catalog, args.batch)
        elif args.command == "validate":
            from .validation import validate
            output = validate(args.catalog)
            print(json.dumps(output, indent=2))
            return 0 if output["valid"] else 1
        elif args.command == "export":
            from .exports import export_catalog
            with catalog_lock(args.catalog):
                store, catalog, current = load_catalog(args.catalog)
                path, manifest = export_catalog(store, catalog, current["catalog"])
                output = {"export_path": str(store.root / path), "manifest": manifest}
        else:
            _, catalog, current = load_catalog(args.catalog)
            output = {"summary": catalog["summary"], "invocation": catalog["invocation"], **current}
        print(json.dumps(output, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

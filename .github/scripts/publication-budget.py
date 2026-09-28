#!/usr/bin/env python3
"""Reject oversized generated files before a Git push or Pages deployment."""
import argparse
from pathlib import Path


def check(root, *, file_limit=None, total_limit=None):
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"Publication directory does not exist: {root}")
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts]
    sizes = [(path, path.stat().st_size) for path in files]
    too_large = [f"{path.relative_to(root)} ({size:,} bytes)" for path, size in sizes if file_limit is not None and size >= file_limit]
    if too_large:
        raise ValueError("Files exceed the publication limit: " + ", ".join(too_large[:20]))
    total = sum(size for _, size in sizes)
    if total_limit is not None and total >= total_limit:
        raise ValueError(f"Publication uses {total:,} bytes; it must stay below {total_limit:,}")
    return len(files), total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--file-limit", type=int)
    parser.add_argument("--total-limit", type=int)
    args = parser.parse_args()
    count, total = check(args.directory, file_limit=args.file_limit, total_limit=args.total_limit)
    print(f"Publication budget passed: {count:,} files, {total:,} bytes")


if __name__ == "__main__":
    main()

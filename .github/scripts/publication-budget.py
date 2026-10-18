#!/usr/bin/env python3
"""Reject oversized generated files before a Git push or Pages deployment."""
import argparse
import os
from pathlib import Path


def check(root, *, file_limit=None, total_limit=None):
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"Publication directory does not exist: {root}")
    count = total = 0
    too_large = []
    for directory, directories, names in os.walk(root):
        directories[:] = [name for name in directories if name != ".git"]
        for name in names:
            path = Path(directory) / name
            if name == ".git" or not path.is_file():
                continue
            size = path.stat().st_size
            count += 1
            total += size
            if file_limit is not None and size >= file_limit and len(too_large) < 20:
                too_large.append(f"{path.relative_to(root)} ({size:,} bytes)")
    if too_large:
        raise ValueError("Files exceed the publication limit: " + ", ".join(too_large))
    if total_limit is not None and total >= total_limit:
        raise ValueError(f"Publication uses {total:,} bytes; it must stay below {total_limit:,}")
    return count, total


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

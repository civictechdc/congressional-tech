# /// script
# requires-python = ">=3.12"
# dependencies = ["lancedb==0.41.0", "sentence-transformers==6.2.0", "pyyaml==6.0.3"]
# ///
"""Search tk Markdown with a disposable local LanceDB index and local embeddings."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
from functools import cache
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import lancedb
from lancedb.index import FTS
import pyarrow as pa
import yaml

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
FORMAT = {"version": 1, "model": MODEL, "revision": REVISION,
          "tokens": 240, "overlap": 32}
DEFAULT_DB = Path(__file__).resolve().parents[2] / ".cache" / "ticket-search"
DEFAULT_TICKETS = Path(__file__).resolve().parents[2] / ".tickets"
TABLE = "passages"
RESULT_FIELDS = ["path", "repo", "ticket_id", "title", "status", "line", "text", "source_hash"]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@contextmanager
def writer_lock(db_path):
    db_path.mkdir(parents=True, exist_ok=True)
    with (db_path / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another sync is running for this index.") from None
        yield


def read_tickets(roots):
    """Read each source once; reject incomplete input before updating the index."""
    tickets = {}
    for root in roots:
        folder = Path(root)
        if not folder.is_dir():
            raise ValueError(f"Ticket directory is unavailable: {folder}")
        seen = set()
        for path in sorted(folder.glob("*.md")):
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError(f"Ticket changed while reading; retry sync: {path}")
            text = raw.decode("utf-8")
            front = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
            if not front:
                raise ValueError(f"Missing YAML frontmatter: {path}")
            try:
                meta = yaml.safe_load(front[1])
            except yaml.YAMLError as exc:
                raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
            if not isinstance(meta, dict) or not isinstance(meta.get("id"), str):
                raise ValueError(f"Missing string ticket ID: {path}")
            ticket_id = meta["id"]
            if ticket_id in seen:
                raise ValueError(f"Duplicate ticket ID {ticket_id} in {folder}")
            seen.add(ticket_id)
            body = text[front.end():]
            title = re.search(r"^#\s+(.+)$", body, re.M)
            tickets[str(path)] = {
                "path": str(path), "repo": folder.parent.name, "ticket_id": ticket_id,
                "title": title[1].strip() if title else ticket_id,
                "status": str(meta.get("status", "unknown")),
                "source_hash": hashlib.sha256(raw).hexdigest(),
                "body": body, "body_line": text[:front.end()].count("\n") + 1,
            }
    return tickets


@cache
def load_model():
    # Import and load only when changed text or a semantic query needs embeddings.
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(4)
    options = dict(revision=REVISION, device="cpu", trust_remote_code=False)
    try:
        return SentenceTransformer(MODEL, local_files_only=True, **options)
    except OSError:
        return SentenceTransformer(MODEL, **options)


def passages(ticket, model):
    """Use tokenizer offsets to retain original text and locate the matching lines."""
    tokenizer = model.tokenizer
    # Bound title overhead as well as body size so late notes are never truncated.
    title_offsets = tokenizer(ticket["title"], add_special_tokens=False,
                              return_offsets_mapping=True)["offset_mapping"]
    title = ticket["title"][:title_offsets[47][1]] if len(title_offsets) > 48 else ticket["title"]
    prefix = title + "\n\n"
    budget = min(FORMAT["tokens"], model.max_seq_length - 2) - len(
        tokenizer(prefix, add_special_tokens=False)["input_ids"])
    body = ticket["body"]
    offsets = tokenizer(body, add_special_tokens=False, truncation=False, verbose=False,
                        return_offsets_mapping=True)["offset_mapping"]
    if not offsets:
        offsets = [(0, len(body))]
    for ordinal, start in enumerate(range(0, len(offsets), budget - FORMAT["overlap"])):
        end = min(start + budget, len(offsets))
        lo, hi = offsets[start][0], offsets[end - 1][1]
        text = prefix + body[lo:hi]
        if len(tokenizer(text)["input_ids"]) > model.max_seq_length:
            raise ValueError(f"Passage exceeds model limit: {ticket['path']}")
        row = {k: v for k, v in ticket.items() if k not in ("body", "body_line")}
        row.update(chunk_key=f"{ticket['path']}#{ordinal}", text=text,
                   line=ticket["body_line"] + body[:lo].count("\n"))
        yield row
        if end == len(offsets):
            break


def schema(config):
    fields = [(name, pa.string()) for name in [
        "chunk_key", "path", "repo", "ticket_id", "title", "status", "source_hash", "text"]]
    fields += [("line", pa.int64()), ("vector", pa.list_(pa.float32(), 384))]
    return pa.schema(fields, metadata={"ticket_search": json.dumps(config).encode()})


def settings(table):
    config = json.loads(table.schema.metadata[b"ticket_search"])
    if config["format"] != FORMAT:
        raise ValueError("Index format/model changed. Use a fresh --db directory and sync.")
    return config


def ensure_fts(table, changed=False):
    indices = table.list_indices()
    exists = any(index.name == "text_idx" for index in indices)
    if changed or not exists or table.index_stats("text_idx")["num_unindexed_rows"]:
        table.create_index("text", config=FTS(stem=False, remove_stop_words=False), replace=True)


def sync(db_path, ticket_dirs=None):
    started = time.perf_counter()
    with writer_lock(db_path):
        db = lancedb.connect(db_path)
        table = db.open_table(TABLE) if TABLE in db.list_tables().tables else None
        config = settings(table) if table else {"format": FORMAT, "roots": []}
        roots = sorted({str(Path(p).expanduser().resolve()) for p in ticket_dirs}) if ticket_dirs else (
            config["roots"] or [str(DEFAULT_TICKETS)])
        if table and roots != config["roots"]:
            raise ValueError("Ticket directories differ from this index. Use a fresh --db directory.")
        config["roots"] = roots
        tickets = read_tickets(roots)
        old = {row["path"]: row["source_hash"] for row in
               table.search().select(["path", "source_hash"]).limit(None).to_list()} if table else {}
        changed = {path for path, ticket in tickets.items() if old.get(path) != ticket["source_hash"]}
        deleted = set(old) - tickets.keys()
        rows = []
        if changed:
            print(f"Embedding {len(changed)} changed tickets...", file=sys.stderr)
            model = load_model()
            rows = [row for path in sorted(changed) for row in passages(tickets[path], model)]
            vectors = model.encode([row["text"] for row in rows], batch_size=32,
                                   normalize_embeddings=True, show_progress_bar=sys.stderr.isatty())
            for row, vector in zip(rows, vectors, strict=True):
                row["vector"] = vector.tolist()
        if table is None:
            table = db.create_table(TABLE, schema=schema(config), data=rows or None)
        elif changed or deleted:
            affected = "path IN (" + ",".join(literal(p) for p in sorted(changed | deleted)) + ")"
            if rows:
                # One commit replaces changed passages and removes their obsolete tails.
                (table.merge_insert("chunk_key").when_matched_update_all()
                 .when_not_matched_insert_all()
                 .when_not_matched_by_source_delete(affected).execute(rows))
            else:
                table.delete(affected)
        ensure_fts(table, bool(changed or deleted))
        return {"tickets": len(tickets), "changed": len(changed), "deleted": len(deleted),
                "embedded_passages": len(rows), "total_passages": table.count_rows(),
                "seconds": round(time.perf_counter() - started, 3), "roots": roots,
                "database": str(db_path)}


def search(db_path, query, limit=10, status=None, mode="hybrid"):
    if not db_path.is_dir():
        raise ValueError("Index does not exist. Run sync first.")
    table = lancedb.connect(db_path).open_table(TABLE)
    settings(table)
    predicate = f"status = {literal(status)}" if status else "true"
    # Exact ticket IDs should work even though text tokenizers split punctuation.
    exact = (table.search().where(f"ticket_id = {literal(query)}")
             .select(RESULT_FIELDS)
             .limit(None).to_list())
    if exact:
        candidates = sorted((row for row in exact if status is None or row["status"] == status),
                            key=lambda row: (row["path"], row["line"]))
    else:
        total = table.count_rows(predicate)
        if not total:
            return []
        vector = load_model().encode(query, normalize_embeddings=True).tolist() if mode != "fts" else None
        take = min(total, max(40, limit * 8))
        while True:
            if mode == "hybrid":
                builder = table.search(query_type="hybrid").vector(vector).text(query).distance_type("cosine")
            elif mode == "vector":
                builder = table.search(vector).distance_type("cosine").select(RESULT_FIELDS + ["_distance"])
            else:
                builder = table.search(query, query_type="fts").select(RESULT_FIELDS + ["_score"])
            candidates = (builder.where(predicate, prefilter=True).limit(take)
                          .to_list())
            if len({row["path"] for row in candidates}) >= limit or take >= total:
                break
            take = min(total, take * 2)
    results = {}
    for row in candidates:
        if row["path"] not in results:
            results[row["path"]] = {k: v for k, v in row.items()
                                   if k in RESULT_FIELDS or k in ("_score", "_distance", "_relevance_score")}
        if len(results) == limit:
            break
    return list(results.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Disposable local index directory")
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("sync", help="Index new/changed tickets and remove deleted files")
    refresh.add_argument("--tickets", action="append", help="Explicit .tickets directory; repeat for multiple repositories")
    find = commands.add_parser("search", help="Search the last synced snapshot")
    find.add_argument("query", nargs="?")
    find.add_argument("--stdin", action="store_true",
                      help="Read one query per line; emit one JSON array per query and reuse the model")
    find.add_argument("--limit", type=int, default=10)
    find.add_argument("--status", choices=["open", "in_progress", "closed"])
    find.add_argument("--mode", choices=["hybrid", "vector", "fts"], default="hybrid")
    find.add_argument("--json", action="store_true", help="Return full matching passages as JSON")
    args = parser.parse_args()
    args.db = args.db.expanduser().resolve()
    try:
        if args.command == "sync":
            print(json.dumps(sync(args.db, args.tickets), indent=2))
        else:
            if args.stdin and args.query is not None:
                raise ValueError("Use a query or --stdin, not both.")
            if args.limit < 1 or (not args.stdin and not (args.query or "").strip()):
                raise ValueError("Use a nonempty query and a positive --limit.")
            queries = sys.stdin if args.stdin else [args.query]
            for query in queries:
                if not query.strip():
                    continue
                results = search(args.db, query.strip(), args.limit, args.status, args.mode)
                if args.stdin:
                    print(json.dumps(results), flush=True)
                elif args.json:
                    print(json.dumps(results, indent=2))
                else:
                    for row in results:
                        print(f"{row['repo']}/{row['ticket_id']} [{row['status']}] {row['title']}")
                        print(f"  {row['path']}:{row['line']}")
                        print("  " + " ".join(row["text"].split())[:360] + "\n")
                    if not results:
                        print("No matching tickets.")
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"ticket-search: {exc}\n")


if __name__ == "__main__":
    main()

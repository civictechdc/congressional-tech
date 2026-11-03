---
id: ct-5hnu
status: closed
deps: []
links: [ct-m104, ct-adoh, ct-sw5t]
created: 2026-11-02T19:50:29Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-m104
tags: [mcp, cache, onboarding, chaos-test]
---
# Keep MCP prepared cache valid across st_dev changes, self-heal selection.json in prepare, and include --prepare-if-missing in client_config

On macOS (APFS), stat.st_dev is dynamically assigned at boot/mount time (e.g., 16777231 -> 16777234 across a reboot while st_ino, st_size, st_mtime_ns, st_ctime_ns and SHA-256 remain identical). Because release.py:stamp(path) includes stat.st_dev, every reboot invalidates ~/.cache/congress-explorer-mcp/selection.json and causes load_selection() to fail every MCP tool call with 'Prepared file changed; choose a fresh data directory'. Worse, running 'congress-explorer-mcp prepare' on the same directory also fails with the same error because _prepare() short-circuits into load_selection(root) when release_id matches and retain() rejects a changed previous stamp instead of re-verifying SHA-256. Finally, cli.py:client_config() omits --prepare-if-missing from generated client args.

## Design

Owner: apps/explorer_mcp/src/congressional_explorer_mcp/release.py and cli.py.
1. Remove `stat.st_dev` from `stamp(path)` (`return [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]`), and add `same_stamp(path, recorded)` (`isinstance(recorded, list) and len(recorded) in (4, 5) and stamp(path) == recorded[-4:]`) used in `retain()` (`release.py:132`) and `load_selection()` (`release.py:224`).
   - Do **not** fall back to full-file SHA-256 hashing when `st_ino`, `st_size`, `st_mtime_ns`, or `st_ctime_ns` differs, and do **not** wrap `load_selection(root)` in `try/except ExplorerError` inside `_prepare()` (`release.py:188-189`). This preserves O(1) `stat()` startup validation across macOS reboots for both existing 5-element and new 4-element `selection.json` files without re-hashing 55–180 MB of Parquet files on every boot, and keeps `test_changed_cache_and_concurrent_prepare_are_rejected` (`test_release.py:83-95`, which tests `path.chmod(0o644)` raising `ExplorerError(match='changed')`) 100% intact.
   - In `_prepare()` (`release.py:188-189`), guard the short-circuit to `load_selection(root)` on `all(Path(f['path']).exists() and not Path(f['path']).is_symlink() and len(f.get('stamp', ())) == 4 for f in previous.get('files', {}).values())` so that if an object file is missing (cache miss) or `selection.json` still has legacy 5-element stamps, `_prepare()` runs the `retain()` loop (re-fetching only missing objects, verifying existing objects via `same_stamp()` without re-reading Parquet footers/payloads per `test_release.py:17-31`, and atomically rewriting `selection.json` with 4-element stamps) while still rejecting tampered existing objects (`test_release.py:93-94`).
2. In `cli.py:client_config()` (`cli.py:18`), include `'--prepare-if-missing'` in `args=['-m', 'congressional_explorer_mcp.cli', 'serve', '--prepare-if-missing', '--data-dir', str(data_dir)]` to match `desktop.py`.
3. In `cli.py:69-73`, when `args.command == 'serve' and args.prepare_if_missing`: if `(args.data_dir / 'selection.json').exists()`, load `selection = load_selection(args.data_dir)` at startup and pass `selection` to `create_server(selection, timeout=args.query_timeout)` so `openWorldHint` (`server.py:51`) stays `False` and custody is validated eagerly when already prepared; only pass `selection=None, data_dir=args.data_dir` when `selection.json` does not exist yet.

## Acceptance Criteria

- `stamp(path)` returns `[st_ino, st_size, st_mtime_ns, st_ctime_ns]`, and `same_stamp(path, recorded)` accepts both 4-element stamps and legacy 5-element stamps whose trailing 4 elements match, surviving `st_dev` changes across macOS reboots in O(1) `stat()` time without re-reading Parquet payloads.
- `test_changed_cache_and_concurrent_prepare_are_rejected` (`test_release.py:83-95`) and `test_same_release_reuses_verified_files_without_payload_or_footer_reads` (`test_release.py:17-31`) pass unchanged (`chmod 0o644` or modified bytes still raise `'Prepared file changed; choose a fresh data directory'`).
- `congress-explorer-mcp config --client <client>` includes `'--prepare-if-missing'` in `args`, and `serve --prepare-if-missing` loads `selection.json` eagerly when present so `openWorldHint` is `False`.


## Notes

**2026-11-03T14:38:09Z**

Completed, verified (123 passed in explorer-mcp lane), and published in congress-mcp-v0.5.0 (d675e540).

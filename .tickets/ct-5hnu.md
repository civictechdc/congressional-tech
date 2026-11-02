---
id: ct-5hnu
status: open
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
1. Remove stat.st_dev from stamp(path) (keep [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]), and treat stamp comparison in load_selection() and retain() as a fast path: if a cached file in objects/<sha256> has a mismatched stamp (including legacy 5-element stamps from existing selection.json files), verify that target is not a symlink, target.stat().st_size == expected_size, and file_digest(stream, 'sha256').hexdigest() == sha256. Only raise 'Prepared file changed; choose a fresh data directory' when the file size or SHA-256 digest actually differs or the path is a symlink.
2. In _prepare() (release.py:188-189), when previous.get('release_id') == manifest['release_id'] and previous.get('archive_origin') == origin, wrap load_selection(root) in try/except ExplorerError so that if selection.json or any cached object fails validation, _prepare() falls through to the retain() loop and atomically rewrites selection.json.
3. In cli.py:client_config(), include '--prepare-if-missing' in args=['-m', 'congressional_explorer_mcp.cli', 'serve', '--prepare-if-missing', '--data-dir', str(data_dir)] to match desktop.py.

## Acceptance Criteria

- A prepared data directory whose selection.json contains a 5-element stamp with a different st_dev (or a touched mtime/ctime with unchanged bytes and size) loads cleanly in load_selection() and retain() after SHA-256 verification, while a modified byte or truncated file still raises 'Prepared file changed; choose a fresh data directory'.
- Running 'congress-explorer-mcp prepare' against a data directory with a stale stamp or missing object self-heals selection.json without requiring manual deletion.
- 'congress-explorer-mcp config --client <client>' includes '--prepare-if-missing' in args.


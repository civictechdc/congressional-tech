"""Digest-pinned RefSpec agency registry input loader and verifier."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import tempfile
import urllib.request
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = pathlib.Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = ROOT / 'model' / 'jobs' / 'refspec' / 'refspec.json'

REQUIRED_TABLES = ('organizations', 'aliases', 'current_successors')

_EMPTY_SCHEMAS: dict[str, pa.Schema] = {
    'organizations': pa.schema([
        pa.field('resource_iri', pa.string(), nullable=False),
        pa.field('fr_id', pa.int64(), nullable=False),
        pa.field('slug', pa.string(), nullable=False),
        pa.field('name', pa.string(), nullable=False),
        pa.field('short_name', pa.string(), nullable=True),
        pa.field('parent', pa.string(), nullable=True),
        pa.field('regulations_gov_codes', pa.list_(pa.string()), nullable=False),
        pa.field('current_successors', pa.list_(pa.string()), nullable=False),
    ]),
    'aliases': pa.schema([
        pa.field('alias_id', pa.string(), nullable=False),
        pa.field('name_key', pa.string(), nullable=False),
        pa.field('target', pa.string(), nullable=True),
        pa.field('target_release_key', pa.string(), nullable=True),
        pa.field('target_publisher_name', pa.string(), nullable=True),
        pa.field('fr_resource', pa.string(), nullable=True),
        pa.field('fr_publisher_name', pa.string(), nullable=True),
        pa.field('fr_relation', pa.string(), nullable=True),
        pa.field('basis', pa.list_(pa.string()), nullable=False),
        pa.field('reasoning', pa.string(), nullable=False),
    ]),
    'current_successors': pa.schema([
        pa.field('original', pa.string(), nullable=False),
        pa.field('successor', pa.string(), nullable=False),
    ]),
}


def _strip_sha256_prefix(value: str) -> str:
  text = str(value).strip()
  return text[7:] if text.startswith('sha256:') else text


def _digest(path: pathlib.Path) -> tuple[str, int]:
  h = hashlib.sha256()
  size = 0
  with path.open('rb') as handle:
    while chunk := handle.read(1 << 20):
      h.update(chunk)
      size += len(chunk)
  return h.hexdigest(), size


def _verify_file(
    path: pathlib.Path,
    *,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    expected_rows: int | None = None,
    label: str = 'file',
) -> tuple[str, int]:
  if not path.is_file():
    raise FileNotFoundError(f'Missing pinned RefSpec {label}: {path}')
  actual_sha, actual_size = _digest(path)
  if expected_size is not None and actual_size != int(expected_size):
    raise ValueError(
        f'RefSpec {label} size mismatch for {path.name}: '
        f'expected {expected_size}, got {actual_size}'
    )
  if expected_sha256 is not None:
    want = _strip_sha256_prefix(expected_sha256)
    if actual_sha != want:
      raise ValueError(
          f'RefSpec {label} sha256 mismatch for {path.name}: '
          f'expected {want}, got {actual_sha}'
      )
  if expected_rows is not None:
    actual_rows = pq.read_metadata(path).num_rows
    if actual_rows != int(expected_rows):
      raise ValueError(
          f'RefSpec {label} row count mismatch for {path.name}: '
          f'expected {expected_rows}, got {actual_rows}'
      )
  return actual_sha, actual_size


def _safe_child(base: pathlib.Path, rel: str) -> pathlib.Path:
  rel_path = pathlib.Path(rel)
  if rel_path.is_absolute():
    raise ValueError(f'RefSpec path must be relative, got {rel!r}')
  resolved_base = base.resolve()
  resolved = (resolved_base / rel_path).resolve()
  if not resolved.is_relative_to(resolved_base):
    raise ValueError(f'RefSpec path escapes manifest directory: {rel!r}')
  return resolved


def _download(url: str, dest: pathlib.Path, expected: dict[str, Any], label: str) -> pathlib.Path:
  if not str(url).startswith('https://'):
    raise ValueError(f'RefSpec URL must use https://, got {url!r}')
  dest.parent.mkdir(parents=True, exist_ok=True)
  req = urllib.request.Request(url, headers={'User-Agent': 'congressional-tech-refspec/1.0'})
  with urllib.request.urlopen(req, timeout=60) as resp:
    data = resp.read()
  sha = hashlib.sha256(data).hexdigest()
  size = len(data)
  if expected.get('size') is not None and size != int(expected['size']):
    raise ValueError(
        f'RefSpec {label} download size mismatch: expected {expected["size"]}, got {size}'
    )
  if expected.get('sha256') is not None:
    want = _strip_sha256_prefix(expected['sha256'])
    if sha != want:
      raise ValueError(
          f'RefSpec {label} download sha256 mismatch: expected {want}, got {sha}'
      )
  with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
    tmp.write(data)
    tmp_path = pathlib.Path(tmp.name)
  tmp_path.replace(dest)
  if expected.get('rows') is not None:
    _verify_file(dest, expected_rows=int(expected['rows']), label=label)
  return dest


def load_refspec_manifest(
    manifest_path: str | pathlib.Path = DEFAULT_MANIFEST,
    *,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> tuple[dict[str, Any], pathlib.Path]:
  path = pathlib.Path(manifest_path).resolve()
  _verify_file(
      path,
      expected_sha256=expected_sha256,
      expected_size=expected_size,
      label='manifest',
  )
  manifest = json.loads(path.read_text(encoding='utf-8'))
  if manifest.get('source') != 'refspec':
    raise ValueError(f'Expected RefSpec manifest source="refspec", got {manifest.get("source")!r}')
  tables = manifest.get('tables')
  if not isinstance(tables, dict):
    raise ValueError('RefSpec manifest missing tables mapping')
  missing = [name for name in REQUIRED_TABLES if name not in tables]
  if missing:
    raise ValueError(f'RefSpec manifest missing required tables: {missing}')
  return manifest, path.parent


def _verify_view_manifest(
    view_manifest_path: pathlib.Path,
    manifest: dict[str, Any],
    base_dir: pathlib.Path,
) -> dict[str, Any]:
  view_pin = manifest.get('view_manifest') or {}
  _verify_file(
      view_manifest_path,
      expected_sha256=view_pin.get('sha256'),
      expected_size=view_pin.get('size'),
      label='view-manifest',
  )
  view_manifest = json.loads(view_manifest_path.read_text(encoding='utf-8'))
  if view_manifest.get('schemaVersion') != manifest.get('schema_version'):
    raise ValueError(
        f'RefSpec view-manifest schemaVersion {view_manifest.get("schemaVersion")!r} '
        f'does not match manifest {manifest.get("schema_version")!r}'
    )
  if view_manifest.get('release') != manifest.get('release'):
    raise ValueError('RefSpec view-manifest release metadata does not match manifest')
  view_dir = view_manifest_path.parent
  members = {m['path']: m for m in view_manifest.get('members') or []}
  for name, entry in manifest['tables'].items():
    if 'path' in entry:
      table_path = _safe_child(base_dir, entry['path']).resolve()
      try:
        rel_to_view = table_path.relative_to(view_dir.resolve()).as_posix()
      except ValueError:
        continue
      member = members.get(rel_to_view)
      if member is None:
        raise ValueError(f'RefSpec table {name} ({rel_to_view}) absent from view-manifest.json')
      if _strip_sha256_prefix(member['sha256']) != _strip_sha256_prefix(entry['sha256']):
        raise ValueError(f'RefSpec table {name} sha256 disagrees with view-manifest.json')
      if int(member['byteLength']) != int(entry['size']):
        raise ValueError(f'RefSpec table {name} byteLength disagrees with view-manifest.json')
      if int(member['rowCount']) != int(entry['rows']):
        raise ValueError(f'RefSpec table {name} rowCount disagrees with view-manifest.json')
  return view_manifest


def fetch_pinned(
    manifest_path: str | pathlib.Path = DEFAULT_MANIFEST,
    *,
    cache_dir: str | pathlib.Path | None = None,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    offline: bool = True,
) -> dict[str, pathlib.Path]:
  manifest, base_dir = load_refspec_manifest(
      manifest_path,
      expected_sha256=expected_sha256,
      expected_size=expected_size,
  )
  resolved: dict[str, pathlib.Path] = {}
  cache_root = pathlib.Path(cache_dir).resolve() if cache_dir is not None else None
  for name, entry in manifest['tables'].items():
    if not isinstance(entry, dict) or not entry.get('sha256') or 'size' not in entry:
      raise ValueError(f'RefSpec table {name!r} must pin sha256 and size')
    rel_path = entry.get('path')
    url = entry.get('url')
    if rel_path is not None:
      path = _safe_child(base_dir, rel_path)
      if path.exists():
        _verify_file(
            path,
            expected_sha256=entry['sha256'],
            expected_size=entry['size'],
            expected_rows=entry.get('rows'),
            label=f'table {name}',
        )
        resolved[name] = path
        continue
      if url is None or offline:
        raise FileNotFoundError(f'Missing pinned RefSpec table {name}: {path}')
      dest = (cache_root / rel_path) if cache_root is not None else path
    elif url is not None:
      if cache_root is None:
        raise ValueError(f'RefSpec remote table {name} requires cache_dir')
      dest = cache_root / f'{name}.parquet'
      if dest.exists():
        _verify_file(
            dest,
            expected_sha256=entry['sha256'],
            expected_size=entry['size'],
            expected_rows=entry.get('rows'),
            label=f'table {name}',
        )
        resolved[name] = dest
        continue
      if offline:
        raise FileNotFoundError(f'RefSpec table {name} absent from cache in offline mode: {dest}')
    else:
      raise ValueError(f'RefSpec table {name!r} must specify path or url')
    resolved[name] = _download(url, dest, entry, label=f'table {name}')

  view_pin = manifest.get('view_manifest')
  if isinstance(view_pin, dict) and view_pin.get('path'):
    view_manifest_path = _safe_child(base_dir, view_pin['path'])
    _verify_view_manifest(view_manifest_path, manifest, base_dir)

  return resolved


def write_empty_refspec_tables(scratch: pathlib.Path) -> dict[str, pathlib.Path]:
  out_dir = scratch / 'refspec-empty'
  out_dir.mkdir(parents=True, exist_ok=True)
  paths: dict[str, pathlib.Path] = {}
  for name, schema in _EMPTY_SCHEMAS.items():
    target = out_dir / f'{name}.parquet'
    pq.write_table(schema.empty_table(), target)
    paths[name] = target
  return paths


def refspec_tables_from_manifest(text: str, base_dir: pathlib.Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
  """Parse a verified refspec.json manifest and return its metadata + local table pins."""
  manifest = json.loads(text)
  if manifest.get('source') != 'refspec':
    raise ValueError(f'Expected RefSpec manifest source="refspec", got {manifest.get("source")!r}')
  tables = manifest.get('tables')
  if not isinstance(tables, dict):
    raise ValueError('RefSpec manifest missing tables mapping')
  missing = [name for name in REQUIRED_TABLES if name not in tables]
  if missing:
    raise ValueError(f'RefSpec manifest missing required tables: {missing}')
  pinned: dict[str, dict[str, Any]] = {}
  for name, entry in sorted(tables.items()):
    if not isinstance(entry, dict) or not entry.get('sha256') or 'size' not in entry or not entry.get('path'):
      raise ValueError(f'RefSpec table {name!r} must pin path, sha256, and size')
    pinned[name] = dict(entry, path=str(_safe_child(base_dir, entry['path'])))
  view_pin = manifest.get('view_manifest')
  if isinstance(view_pin, dict) and view_pin.get('path'):
    pinned['_view_manifest'] = dict(view_pin, path=str(_safe_child(base_dir, view_pin['path'])))
  return manifest, pinned


def refspec_profile_pin(refspec: str | pathlib.Path | dict[str, Any] | None) -> dict[str, Any] | None:
  if refspec is None:
    return None
  if isinstance(refspec, dict) and 'pin' in refspec and 'tables' in refspec:
    return dict(refspec['pin'])
  if isinstance(refspec, dict):
    manifest_path = pathlib.Path(refspec['path']).resolve()
    expected_sha = refspec.get('sha256')
    expected_size = refspec.get('size')
  else:
    manifest_path = pathlib.Path(refspec).resolve()
    expected_sha = None
    expected_size = None
  manifest, _base = load_refspec_manifest(
      manifest_path,
      expected_sha256=expected_sha,
      expected_size=expected_size,
  )
  sha, size = _digest(manifest_path)
  return {
      'sha256': sha,
      'size': size,
      'schema_version': manifest['schema_version'],
      'release_key': manifest['release']['key'],
      'view_manifest_sha256': _strip_sha256_prefix(
          (manifest.get('view_manifest') or {}).get('sha256', '')
      ),
  }


def refspec_model_inputs(
    refspec: str | pathlib.Path | dict[str, Any] | None,
    scratch: pathlib.Path,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
  if refspec is None:
    tables = write_empty_refspec_tables(scratch)
    pin_info = None
    inputs = [
        dict(name='refspec_organizations', path=str(tables['organizations']), kind='parquet'),
        dict(name='refspec_aliases', path=str(tables['aliases']), kind='parquet'),
        dict(
            name='refspec_current_successors',
            path=str(tables['current_successors']),
            kind='parquet',
        ),
    ]
    return inputs, pin_info

  if isinstance(refspec, dict) and 'tables' in refspec:
    table_map = refspec['tables']
    inputs = [
        dict(table_map['organizations'], name='refspec_organizations', kind='parquet'),
        dict(table_map['aliases'], name='refspec_aliases', kind='parquet'),
        dict(table_map['current_successors'], name='refspec_current_successors', kind='parquet'),
    ]
    return inputs, (dict(refspec['pin']) if 'pin' in refspec else None)

  if isinstance(refspec, dict):
    manifest_path = pathlib.Path(refspec['path']).resolve()
    expected_sha = refspec.get('sha256')
    expected_size = refspec.get('size')
  else:
    manifest_path = pathlib.Path(refspec).resolve()
    expected_sha = None
    expected_size = None
  tables = fetch_pinned(
      manifest_path,
      expected_sha256=expected_sha,
      expected_size=expected_size,
      offline=True,
  )
  pin_info = refspec_profile_pin(refspec)
  inputs = [
      dict(name='refspec_organizations', path=str(tables['organizations']), kind='parquet'),
      dict(name='refspec_aliases', path=str(tables['aliases']), kind='parquet'),
      dict(
          name='refspec_current_successors',
          path=str(tables['current_successors']),
          kind='parquet',
      ),
  ]
  return inputs, pin_info


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description='Verify pinned RefSpec agency registry inputs.')
  group = parser.add_mutually_exclusive_group()
  group.add_argument('--manifest', default=str(DEFAULT_MANIFEST), help='Path to refspec.json')
  group.add_argument('--model-spec', help='Verify the refspec block inside a model spec JSON')
  parser.add_argument('--cache-dir', help='Optional cache directory for remote RefSpec tables')
  parser.add_argument('--online', action='store_true', help='Allow downloading remote tables')
  parser.add_argument('--json', action='store_true', help='Print verified paths as JSON')
  args = parser.parse_args(argv)

  if args.model_spec:
    spec_path = pathlib.Path(args.model_spec).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    ref_pin = spec.get('refspec')
    if not isinstance(ref_pin, dict) or not ref_pin.get('path'):
      raise ValueError(f'Model spec {spec_path} has no refspec pin')
    manifest_path = (spec_path.parent / ref_pin['path']).resolve()
    tables = fetch_pinned(
        manifest_path,
        cache_dir=args.cache_dir,
        expected_sha256=ref_pin.get('sha256'),
        expected_size=ref_pin.get('size'),
        offline=not args.online,
    )
  else:
    tables = fetch_pinned(
        args.manifest,
        cache_dir=args.cache_dir,
        offline=not args.online,
    )

  if args.json:
    print(json.dumps({k: str(v) for k, v in sorted(tables.items())}, indent=2))
  else:
    for name, path in sorted(tables.items()):
      print(f'{name}: {path}')
  return 0


if __name__ == '__main__':
  sys.exit(main())

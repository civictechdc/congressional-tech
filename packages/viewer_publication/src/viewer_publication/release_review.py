"""Human-readable Gate-1 review summaries and bounded before/after row samples."""
import json
from pathlib import Path
import re

import duckdb

from viewer_publication.release_comparison import identities as _table_identities

MECHANICAL_PIN_COLUMNS = frozenset({'source_generation', 'source_reference'})
URL_STATE_ROUTINE_COLUMNS = frozenset({
    'attempts', 'last_attempt', 'last_status', 'last_outcome', 'last_good_at',
    'next_attempt_at', 'recheck_meeting_date', 'linked_from', 'capture_reason',
})
CONTEXT_COLUMNS = (
    'title', 'filename', 'name', 'url', 'video_key', 'event_id', 'bill_id',
    'nomination_id', 'meeting_date', 'document_kind', 'title_source', 'note',
)
MAX_SAMPLE_ROWS_FOR_JOINS = 500_000
MAX_CELL_CHARS = 120


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _format_cell(value, limit=MAX_CELL_CHARS):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value).hex()
        return raw if len(raw) <= limit else raw[:limit - 3] + '...'
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        text = json.dumps(value, default=str, ensure_ascii=False)
    else:
        text = str(value)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 3] + '...'


def _format_key(row_dict):
    if len(row_dict) == 1:
        only = next(iter(row_dict.values()))
        return _format_cell(only, limit=80)
    return ', '.join(f'{k}={_format_cell(v, limit=48)}' for k, v in row_dict.items())


def _group_id(entry):
    if 'id' in entry:
        return entry['id']
    return f"{entry['file']}|{entry['group']}|{entry['cause']}"


def is_mechanical_pin_group(entry, report=None):
    """True for routine upstream pin-stamp or byte-only rewrites that do not alter content."""
    group = entry.get('group', '')
    file_name = entry.get('file') or entry.get('id', '').split('|', 1)[0]
    if group in ('changed bytes, no key or value difference found',):
        return True
    if group.startswith('changed '):
        col = group.removeprefix('changed ')
        if col in MECHANICAL_PIN_COLUMNS:
            return True
        if col == 'bill_references' and file_name == 'roll_call_votes.parquet' and report:
            rcv_groups = {g.get('group') for g in report.get('files', {}).get(file_name, {}).get('groups', ())}
            ba_groups = {g.get('group') for g in report.get('files', {}).get('bill_actions.parquet', {}).get('groups', ())}
            if 'changed source_generation' in rcv_groups or 'changed source_generation' in ba_groups:
                return True
    return False


def is_routine_addition_group(entry):
    """True for verified or capture-churn groups that belong in the collapsed appendix."""
    file_name = entry.get('file') or entry.get('id', '').split('|', 1)[0]
    group = entry.get('group', '')
    count = entry.get('count', 0)
    if count < 0 or entry.get('flag') or entry.get('status') == 'unexplained':
        return False
    if file_name == 'url_state.parquet' and group.startswith('changed '):
        return group.removeprefix('changed ') in URL_STATE_ROUTINE_COLUMNS
    return group in ('added keys', 'added rows', 'added bills', 'new URLs', 'keys new', 'added URLs')


def _parquet_columns(con, path: Path) -> list[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{str(path).replace(chr(39), chr(39)*2)}')").fetchall()
    return [row[0] for row in rows]


def _pick_context_columns(columns: list[str], key_fields: list[str]) -> list[str]:
    key_set = set(key_fields)
    return [col for col in CONTEXT_COLUMNS if col in columns and col not in key_set][:3]


def _row_count(report, file_name: str, side: str):
    rows = report.get('files', {}).get(file_name, {}).get('rows')
    return rows.get(side) if isinstance(rows, dict) else None


def write_review_samples(report, base_dir, candidate_dir, out_path, *, max_per_group=5):
    """Write bounded before/after row samples for stopped-night tables and return the dict."""
    base_dir = Path(base_dir)
    candidate_dir = Path(candidate_dir)
    out_path = Path(out_path)
    id_map = _table_identities({'base': base_dir, 'candidate': candidate_dir})

    interesting_files = set()
    for name, facts in report.get('files', {}).items():
        for g in facts.get('groups', ()):
            if g.get('count', 0) < 0 or g.get('status') != 'verified':
                interesting_files.add(name)

    tables = {}
    con = duckdb.connect()
    try:
        con.execute('PRAGMA threads=2')
        for file_name in sorted(interesting_files):
            if not file_name.endswith('.parquet'):
                continue
            table_name = file_name.removesuffix('.parquet')
            base_path = base_dir / file_name
            cand_path = candidate_dir / file_name
            if not base_path.exists() or not cand_path.exists():
                continue
            fields = (id_map.get(table_name) or {}).get('fields') or []
            if not fields:
                tables[file_name] = {'skipped': 'no registered primary key'}
                continue
            if 'list_row' in fields:
                tables[file_name] = {'skipped': 'release-local list_row identity'}
                continue

            base_q = f"read_parquet('{str(base_path).replace(chr(39), chr(39)*2)}')"
            cand_q = f"read_parquet('{str(cand_path).replace(chr(39), chr(39)*2)}')"
            try:
                base_cols = _parquet_columns(con, base_path)
                cand_cols = _parquet_columns(con, cand_path)
                if not all(f in base_cols and f in cand_cols for f in fields):
                    tables[file_name] = {'skipped': 'primary key columns differ between releases'}
                    continue

                entry = {}
                groups = report.get('files', {}).get(file_name, {}).get('groups', ())
                has_removed = any(g.get('count', 0) < 0 for g in groups)
                has_added = any(g.get('count', 0) > 0 and ('added' in g.get('group', '') or 'new' in g.get('group', '').lower()) for g in groups)
                base_rows = _row_count(report, file_name, 'base')
                cand_rows = _row_count(report, file_name, 'candidate')

                using_clause = ', '.join(_quote_ident(f) for f in fields)
                order_clause = ', '.join(_quote_ident(f) for f in fields)

                if has_removed:
                    ctx_cols = _pick_context_columns(base_cols, fields)
                    select_cols = [*fields, *ctx_cols]
                    sel = ', '.join(f'p.{_quote_ident(c)}' for c in select_cols)
                    rows = con.execute(
                        f'SELECT {sel} FROM {base_q} p ANTI JOIN {cand_q} l USING({using_clause}) '
                        f'ORDER BY {order_clause} LIMIT {int(max_per_group)}'
                    ).fetchall()
                    entry['removed'] = [
                        {c: _format_cell(v) for c, v in zip(select_cols, row)}
                        for row in rows
                    ]

                large_table = (base_rows is not None and base_rows > MAX_SAMPLE_ROWS_FOR_JOINS) or (
                    cand_rows is not None and cand_rows > MAX_SAMPLE_ROWS_FOR_JOINS
                )
                if has_added:
                    if large_table:
                        entry['added_skipped'] = f'skipped sampling on {cand_rows} rows (> {MAX_SAMPLE_ROWS_FOR_JOINS})'
                    else:
                        ctx_cols = _pick_context_columns(cand_cols, fields)
                        select_cols = [*fields, *ctx_cols]
                        sel = ', '.join(f'l.{_quote_ident(c)}' for c in select_cols)
                        rows = con.execute(
                            f'SELECT {sel} FROM {cand_q} l ANTI JOIN {base_q} p USING({using_clause}) '
                            f'ORDER BY {order_clause} LIMIT {int(max_per_group)}'
                        ).fetchall()
                        entry['added'] = [
                            {c: _format_cell(v) for c, v in zip(select_cols, row)}
                            for row in rows
                        ]

                changed_cols = [
                    g.get('group', '').removeprefix('changed ')
                    for g in groups
                    if g.get('status') != 'verified'
                    and g.get('value')
                    and g.get('group', '').startswith('changed ')
                    and not is_mechanical_pin_group({'file': file_name, **g}, report)
                    and not is_routine_addition_group({'file': file_name, **g})
                ]
                common_cols = set(base_cols) & set(cand_cols)
                changed_cols = [c for c in changed_cols if c in common_cols and c not in fields]
                if changed_cols:
                    if large_table:
                        entry['changed_skipped'] = f'skipped column diff sampling on {base_rows} rows (> {MAX_SAMPLE_ROWS_FOR_JOINS})'
                    else:
                        on_clause = ' AND '.join(f'p.{_quote_ident(f)} = l.{_quote_ident(f)}' for f in fields)
                        agg_terms = []
                        for col in changed_cols:
                            qc = _quote_ident(col)
                            agg_terms.extend([
                                f'count(*) FILTER (WHERE p.{qc} IS NULL AND l.{qc} IS NOT NULL)',
                                f'count(*) FILTER (WHERE p.{qc} IS NOT NULL AND l.{qc} IS NULL)',
                                f'count(*) FILTER (WHERE p.{qc} IS NOT NULL AND l.{qc} IS NOT NULL AND p.{qc} IS DISTINCT FROM l.{qc})',
                            ])
                        counts_row = con.execute(
                            f'SELECT {", ".join(agg_terms)} FROM {base_q} p JOIN {cand_q} l ON {on_clause}'
                        ).fetchone()
                        col_samples = {}
                        key_sel = ', '.join(f'p.{_quote_ident(f)}' for f in fields)
                        for idx, col in enumerate(changed_cols):
                            n2v, v2n, v2v = counts_row[idx * 3:(idx + 1) * 3]
                            qc = _quote_ident(col)
                            sample_rows = con.execute(
                                f'SELECT {key_sel}, p.{qc}, l.{qc} '
                                f'FROM {base_q} p JOIN {cand_q} l ON {on_clause} '
                                f'WHERE p.{qc} IS DISTINCT FROM l.{qc} '
                                f'ORDER BY {", ".join("p." + _quote_ident(f) for f in fields)} '
                                f'LIMIT {int(max_per_group)}'
                            ).fetchall()
                            n_keys = len(fields)
                            col_samples[col] = {
                                'none_to_val': int(n2v),
                                'val_to_none': int(v2n),
                                'val_to_val': int(v2v),
                                'samples': [
                                    {
                                        'key': _format_key(dict(zip(fields, row[:n_keys]))),
                                        'before': _format_cell(row[n_keys]),
                                        'after': _format_cell(row[n_keys + 1]),
                                    }
                                    for row in sample_rows
                                ],
                            }
                        entry['changed_columns'] = col_samples
                if entry:
                    tables[file_name] = entry
            except Exception as exc:
                tables[file_name] = {'skipped': f'{type(exc).__name__}: {exc}'}
    finally:
        con.close()

    payload = {
        'version': 1,
        'base_release': report.get('base_release'),
        'candidate_release': report.get('candidate_release'),
        'max_per_group': int(max_per_group),
        'tables': tables,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1, default=str) + '\n')
    return payload


def _removed_examples_for_file(file_name: str, report: dict, samples: dict | None, limit=3) -> str:
    tables = (samples or {}).get('tables', {})
    removed = (tables.get(file_name) or {}).get('removed') or []
    if removed:
        rendered = []
        for row in removed[:limit]:
            # Show key + first context value when compact
            items = [f'{k}={v}' for k, v in row.items() if v is not None]
            rendered.append('`' + ', '.join(items[:2]) + '`')
        return '; '.join(rendered)
    notes = (report.get('files', {}).get(file_name) or {}).get('removed_keys') or []
    if notes:
        return '; '.join('`' + _format_key(item) + '`' for item in notes[:limit])
    return '—'


def render_review_summary(report, *, samples=None, record=None) -> str:
    """Render a compact, plain-English 1-page Gate-1 Markdown summary for PRs and CI logs."""
    base = report.get('base_release') or 'none'
    candidate = report.get('candidate_release') or 'unknown'
    link_rule = report.get('link_rule') or {}
    causes_by_id = {e['id']: e for e in (record or {}).get('groups', ())}
    failing = list(report.get('failing') or [])

    all_removals = []
    for fname, facts in sorted((report.get('files') or {}).items()):
        for g in facts.get('groups', ()):
            if g.get('count', 0) < 0:
                all_removals.append({'file': fname, **g})

    total_removed = sum(-g['count'] for g in all_removals)
    red_flags = []
    seen_red = set()
    for g in all_removals + [
        x for x in failing
        if (x.get('status') == 'unexplained' or x.get('flag')) and not is_mechanical_pin_group(x, report)
    ]:
        gid = _group_id(g)
        if gid not in seen_red:
            seen_red.add(gid)
            red_flags.append(g)

    mechanical = [g for g in failing if _group_id(g) not in seen_red and is_mechanical_pin_group(g, report)]
    routine = [g for g in failing if _group_id(g) not in seen_red and g not in mechanical and is_routine_addition_group(g)]
    content_changes = [g for g in failing if _group_id(g) not in seen_red and g not in mechanical and g not in routine]

    lines = [
        f'# Gate-1 Release Review: `{base[:12]}` → `{candidate[:12]}`',
        '',
        '## At a Glance',
        '',
    ]
    if link_rule.get('ok'):
        lines.append('- ✅ **Links:** 0 broken, changed, or demoted live links')
    else:
        lines.append(
            f"- ❌ **Links:** missing={link_rule.get('missing', 0)}, dangling={link_rule.get('dangling', 0)}, "
            f"changed={link_rule.get('changed', 0)}, demoted={link_rule.get('demoted', 0)}, "
            f"unchecked={len(link_rule.get('unchecked') or [])}"
        )
    if total_removed:
        lines.append(f'- ⚠️ **Removals:** {total_removed:,} removed rows across {len({g["file"] for g in all_removals})} table(s)')
    else:
        lines.append('- ✅ **Removals:** 0 rows removed')
    lines.append(
        f'- 📊 **Groups to review:** {len(content_changes)} content change(s), {len(red_flags)} flag/removal(s) '
        f'({len(mechanical)} mechanical pin-stamp groups & {len(routine)} routine addition/capture groups collapsed below)'
    )
    if causes_by_id:
        lines.append(f'- 📝 **Cause record:** bound ({len(causes_by_id)} entries)')
    lines.append('')

    if red_flags:
        lines += [
            '## 1. Red Flags & Removals',
            '',
            '| File | Group | Count | Status | Examples | Cause |',
            '| --- | --- | ---: | --- | --- | --- |',
        ]
        for g in red_flags:
            gid = _group_id(g)
            ex = _removed_examples_for_file(g['file'], report, samples) if g.get('count', 0) < 0 else '—'
            cause = (causes_by_id.get(gid) or {}).get('cause') or g.get('cause', '')
            if len(cause) > 140:
                cause = cause[:137] + '...'
            lines.append(f"| `{g['file']}` | {g['group']} | {g['count']:,} | {g.get('status', '')} | {ex} | {cause} |")
        lines.append('')

    lines += ['## 2. Content Changes to Spot-Check', '']
    if not content_changes:
        lines += ['_None — all differences are removals/flags above or routine/mechanical updates below._', '']
    else:
        by_file = {}
        for g in content_changes:
            by_file.setdefault(g['file'], []).append(g)
        sample_tables = (samples or {}).get('tables', {})
        for fname, gs in sorted(by_file.items()):
            rows_info = (report.get('files', {}).get(fname) or {}).get('rows') or {}
            delta = (report.get('files', {}).get(fname) or {}).get('delta')
            if isinstance(rows_info, dict) and rows_info.get('base') is not None and rows_info.get('candidate') is not None:
                shown_delta = delta if delta is not None else rows_info['candidate'] - rows_info['base']
                row_summary = f" ({rows_info['base']:,} → {rows_info['candidate']:,}, Δ {shown_delta:+,})"
            else:
                row_summary = ''
            lines.append(f'### `{fname}`{row_summary}')
            col_samples = (sample_tables.get(fname) or {}).get('changed_columns') or {}
            lines += ['| Change | Rows | Direction | Sample (`before` → `after`) |', '| --- | ---: | --- | --- |']
            for g in gs:
                col = g['group'].removeprefix('changed ') if g['group'].startswith('changed ') else None
                cinfo = col_samples.get(col) if col else None
                if cinfo:
                    direction = f"{cinfo['none_to_val']:,} filled, {cinfo['val_to_none']:,} cleared, {cinfo['val_to_val']:,} modified"
                    ex_list = cinfo.get('samples') or []
                    ex = (
                        f"`{ex_list[0]['key']}`: `{ex_list[0]['before']}` → `{ex_list[0]['after']}`"
                        if ex_list
                        else '—'
                    )
                else:
                    direction = g.get('cause', '')
                    ex = '—'
                lines.append(f"| {g['group']} | {g['count']:,} | {direction} | {ex} |")
            lines.append('')

    if mechanical:
        mech_tables = len({g['file'] for g in mechanical})
        lines += [
            '## 3. Mechanical Pin Refreshes & Byte-Only Rewrites',
            '',
            f'Upstream pin re-stamps (`source_generation`, `source_reference`, `bill_references`) and byte-only rewrites: **{len(mechanical)} group(s) across {mech_tables} table(s)**.',
            '',
            '<details>',
            '<summary>Show mechanical groups</summary>',
            '',
            '| File | Group | Count |',
            '| --- | --- | ---: |',
            *(f"| `{g['file']}` | {g['group']} | {g['count']:,} |" for g in mechanical),
            '',
            '</details>',
            '',
        ]

    if routine:
        lines += [
            '## 4. Routine Additions & Capture Queue Updates',
            '',
            f'Routine added keys/URLs and capture-queue updates: **{len(routine)} group(s)**.',
            '',
            '<details>',
            '<summary>Show routine groups</summary>',
            '',
            '| File | Group | Count |',
            '| --- | --- | ---: |',
            *(f"| `{g['file']}` | {g['group']} | {g['count']:,} |" for g in routine),
            '',
            '</details>',
            '',
        ]

    return '\n'.join(lines)

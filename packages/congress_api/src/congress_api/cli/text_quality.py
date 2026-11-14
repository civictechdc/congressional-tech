"""Offline bounded quality measurements and retained-feature review ordering."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from congress_api.lake.text_assessment import assess_text
from congress_api.lake.text_quality import MAX_TEXT_BYTES, POLICY_VERSION, assessment_facts, measure_quality


def _read(path, expected, limit=MAX_TEXT_BYTES):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError(f'artifact exceeds {limit} byte measurement bound: {path}')
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError(f'artifact exceeds {limit} byte measurement bound: {path}')
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f'artifact hash differs: {path}')
    return raw


def _file_digest(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _lines(path, limit):
    with Path(path).open('rb') as stream:
        while line := stream.readline(limit+1):
            if len(line) > limit:
                raise ValueError('JSONL record exceeds byte bound')
            if line.strip():
                yield line


def measure_cases(path, out, limit=32):
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    if type(limit) is not int or not 1 <= limit <= 128:
        raise ValueError('case limit must be between 1 and 128')
    allowed = {'case_id', 'body_sha256', 'parser', 'parser_version', 'text_sha256', 'source_format',
               'output_path', 'output_sha256', 'scope', 'page_number', 'source_page_count',
               'intermediate_path', 'intermediate_sha256', 'intermediate_kind',
               'intermediate_body_sha256', 'intermediate_scope', 'intermediate_page_number',
               'source_state', 'precleanup_available', 'selected',
               'raw_markup_path', 'raw_markup_sha256', 'feature_file'}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    measured_path, proposals_path = out/'measurements.jsonl', out/'proposals.jsonl'
    count, measurement_digest = 0, sha256()
    with measured_path.open('xb') as destination:
        for line in _lines(path, 32 << 10):
            if count >= limit:
                raise ValueError('case limit exceeded; earlier measurements are partial')
            case = json.loads(line)
            if set(case) - allowed:
                raise ValueError('unsupported case fields; source-review labels are not measurement inputs')
            identity = {k: case[k] for k in ('body_sha256', 'parser', 'parser_version', 'text_sha256',
                                           'output_sha256', 'source_format', 'scope')}
            identity.update({k: case.get(k) for k in ('page_number', 'source_page_count', 'intermediate_kind',
                'intermediate_body_sha256', 'intermediate_scope', 'intermediate_page_number', 'precleanup_available')})
            identity['source_state'] = case.get('source_state', 'unknown')
            identity['selected'] = case.get('selected')
            text = _read(case['output_path'], case['output_sha256']).decode('utf-8')
            intermediate = (_read(case['intermediate_path'], case['intermediate_sha256']).decode('utf-8')
                            if case.get('intermediate_path') else None)
            raw = (_read(case['raw_markup_path'], case['raw_markup_sha256'], 1 << 20)
                   if case.get('raw_markup_path') else None)
            feature = None
            if case.get('feature_file'):
                if Path(case['feature_file']).stat().st_size > 16 << 20 or pq.ParquetFile(case['feature_file']).metadata.num_rows > 8192:
                    raise ValueError('point feature part exceeds bounded lookup size')
                predicate = None
                for key in ('body_sha256', 'parser', 'parser_version', 'text_sha256'):
                    term = ds.field(key) == identity[key]
                    predicate = term if predicate is None else predicate & term
                rows = ds.dataset(case['feature_file'], format='parquet').to_table(filter=predicate).to_pylist()
                if len(rows) != 1:
                    raise ValueError('feature file does not contain one exact reading/text identity')
                feature = rows[0]
            measured = measure_quality(identity, text=text, intermediate=intermediate, feature=feature, raw_markup=raw)
            measured.update(case_id=case['case_id'], input_artifacts=case)
            encoded = (json.dumps(measured, ensure_ascii=False, sort_keys=True)+'\n').encode()
            if len(encoded) > 1 << 20:
                raise ValueError('measurement record exceeds byte bound')
            destination.write(encoded)
            measurement_digest.update(encoded)
            count += 1
    evidence_sha = measurement_digest.hexdigest()
    with proposals_path.open('x') as destination:
        for number, line in enumerate(_lines(measured_path, 1 << 20), 1):
            if number > limit:
                raise ValueError('measurement records changed beyond case limit')
            measured = json.loads(line)
            evidence = dict(stage='measurement', path=str(measured_path.resolve()), sha256=evidence_sha,
                            locator=f'line {number}; case {measured["case_id"]}; four separate measured axes')
            proposal = assess_text(assessment_facts(measured, evidence))
            destination.write(json.dumps(dict(case_id=measured['case_id'], proposal=proposal), sort_keys=True)+'\n')
    return {'cases': count, 'measurements': str(measured_path), 'proposals': str(proposals_path),
            'source_fidelity': 'not_established', 'policy_version': POLICY_VERSION}


def rank_features(generation_path, out, recovery_status=None):
    """Read existing feature columns once, then order only the small derived rows."""
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    generation = json.loads(Path(generation_path).read_text())
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    unsorted, ranked = out/'coverage-unsorted.parquet', out/'coverage-ranked.parquet'
    if unsorted.exists() or ranked.exists():
        raise ValueError('ranking output already exists')
    writer = None
    schema = pa.schema([
        *[pa.field(n, pa.string()) for n in ('body_sha256', 'parser', 'parser_version', 'text_sha256',
          'status', 'repetition_scope', 'physical_source_coverage', 'feature_file', 'feature_version',
          'signals', 'stratum', 'recognition', 'cleanup', 'role', 'fts_band', 'fts_reasons')],
        *[pa.field(n, pa.int64()) for n in ('recorded_offset_slots', 'empty_slots', 'interior_empty_slots',
          'longest_interior_empty_run', 'nonocr_empty_slots', 'under_200_slots', 'ocr_slot_count',
          'selected_offset_slot', 'nonspace_characters', 'sparse_under_1000_slots', 'triage_order')],
        *[pa.field(n, pa.float64()) for n in ('under_200_slot_fraction', 'sparse_repeated_line_char_fraction')],
    ])
    rows_seen = slots_seen = 0
    signal_counts, band_counts = {}, {}
    try:
        for part in generation['baseline_parts'] + generation['delta_parts']:
            path = Path(part['path'])
            if _file_digest(path) != part['sha256']:
                raise ValueError('retained feature part hash changed')
            for batch in pq.ParquetFile(path, pre_buffer=False).iter_batches(batch_size=256, use_threads=False):
                pending = []
                for feature in batch.to_pylist():
                    identity = {k: feature[k] for k in ('body_sha256', 'parser', 'parser_version', 'text_sha256')}
                    identity.update(output_sha256=feature['text_sha256'], source_format='pdf', scope='reading',
                                    page_number=None, source_page_count=None)
                    measured = measure_quality(identity, feature=feature)
                    coverage = measured['axes']['coverage']
                    triage = measured['fts_triage']
                    band_counts[triage['band']] = band_counts.get(triage['band'], 0)+1
                    for signal in measured['signals']:
                        signal_counts[signal] = signal_counts.get(signal, 0)+1
                    pending.append({**{k: feature[k] for k in ('body_sha256', 'parser', 'parser_version', 'text_sha256')},
                                    **coverage, 'feature_file': str(path), 'feature_version': feature['feature_version'],
                                    'signals': ','.join(measured['signals']), 'stratum': 'pdf_unknown_source_family',
                                    'fts_band': triage['band'], 'fts_reasons': ','.join(triage['reasons']),
                                    'triage_order': {'review_first': 0, 'review_later': 1, 'no_obvious_failure_detected': 2, 'unassessed': 3}[triage['band']],
                                    'recognition': 'unmeasured', 'cleanup': 'unmeasured', 'role': 'unmeasured'})
                    rows_seen += 1
                    slots_seen += coverage['recorded_offset_slots']
                table = pa.Table.from_pylist(pending, schema=schema)
                if writer is None:
                    writer = pq.ParquetWriter(unsorted, table.schema, compression='zstd')
                writer.write_table(table)
    finally:
        if writer:
            writer.close()
    if rows_seen != generation['combined_rows'] or slots_seen != generation['combined_pdf_slots']:
        raise ValueError('retained feature generation counts differ')
    con = duckdb.connect(config={'threads': '1', 'memory_limit': '256MB'})
    query = '''SELECT row_number() OVER (ORDER BY triage_order, longest_interior_empty_run DESC,
               nonocr_empty_slots DESC, sparse_repeated_line_char_fraction DESC,
               under_200_slot_fraction DESC, body_sha256, parser, parser_version, text_sha256) AS review_order,
               * FROM read_parquet(?) ORDER BY review_order'''
    reader = con.execute(query, [str(unsorted)]).fetch_record_batch(1024)
    with pq.ParquetWriter(ranked, reader.schema, compression='zstd') as result:
        for batch in reader:
            result.write_batch(batch)
    con.close()
    unsorted.unlink()
    summary = {'policy_version': POLICY_VERSION, 'reading_rows': rows_seen, 'recorded_offset_slots': slots_seen,
               'signal_counts': signal_counts, 'fts_band_counts': band_counts, 'ranking': str(ranked),
               'ranking_axes': ['longest_interior_empty_run', 'nonocr_empty_slots',
                                'sparse_repeated_line_char_fraction', 'under_200_slot_fraction'],
               'ranking_method': 'lexicographic_review_order_not_quality_probability',
               'source_payloads_read': 0, 'stratum': 'pdf_unknown_source_family',
               'source_fidelity': 'unknown', 'other_axes': 'unmeasured',
               'scope': 'supplied PDF feature generation only; non-PDF garbling and roles are not comprehensively screened'}
    if recovery_status:
        with Path(recovery_status).open('rb') as stream:
            raw = stream.read((1 << 20)+1)
        if len(raw) > 1 << 20:
            raise ValueError('recovery status metadata exceeds bound')
        state = json.loads(raw)
        summary['separate_recovery_cohort'] = {'status_path': str(recovery_status), 'status_sha256': sha256(raw).hexdigest(),
            'observed_at': state['observed_at'], 'outcomes': state['outcomes'], 'pending': state['remaining_targets'],
            'scope': 'recovery_cohort_only_not_added_to_pdf_feature_counts'}
    (out/'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('measure', 'rank'):
        command = commands.add_parser(name)
        command.add_argument('input', type=Path)
        command.add_argument('--out', type=Path, required=True)
        if name == 'measure':
            command.add_argument('--limit', type=int, default=32)
        else:
            command.add_argument('--recovery-status', type=Path)
    args = parser.parse_args()
    result = measure_cases(args.input, args.out, args.limit) if args.command == 'measure' else rank_features(args.input, args.out, args.recovery_status)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

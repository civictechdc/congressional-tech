"""Add missing GPO metadata from retained XML without claiming a live refresh.

Run with ``python -m congress_api.replay.gpo --help``. Existing scalar corrections,
transcript dates and modification times win over cached inputs. Native bytes are
retained separately, including rosters that do not prove meeting attendance.

Compatibility and source-specific protection rules:
/docs/congress-api-contracts.md#replay-protection-matrix
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from congress_api.acquisition.gpo import GOVINFO_CONTENT
from congress_api.matching.gpo_committees import merge_cached_row
from congress_api.parsers.gpo_hearings import PARSER_VERSION, parse_mods
from congress_api.parsers.xml import MODS_NS, parse_xml
from congress_api.retention import gpo as evidence
from congress_api.retention.gpo import read_csv, write_csv


def replay(input_path, mods_dir, output_path, evidence_path, *, html_dir=None, receipt_path=None):
    rows = read_csv(input_path)
    retained = evidence.read(evidence_path)
    receipt = {'generated_at': datetime.now(timezone.utc).isoformat(),
               'input_sha256': hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
               'input_rows': len(rows), 'mode': 'additive-cached-replay', 'parser_version': PARSER_VERSION,
               'retrieval_time_known': False, 'packages': [], 'failures': [], 'unmatched_cache_files': []}
    for path in sorted(Path(mods_dir).glob('*.xml')):
        package = path.stem
        if package not in rows:
            receipt['unmatched_cache_files'].append(package)
            continue
        old = rows[package]
        try:
            captured = dict(retained.get(package, {}))
            # Acquired observations are protected before interpreting local bytes.
            if captured.get('mods', {}).get('retrieved_at'):
                receipt['packages'].append({'package_id': package, 'status': 'kept-acquired-evidence'})
                continue
            data = path.read_bytes()
            root = parse_xml(data)
            parsed = asdict(parse_mods(package, data, old['last_modified']))
            merged = merge_cached_row(old, parsed)
            captured.update(package_id=package, parser_version=PARSER_VERSION,
                mods=evidence.observation(data, f'{GOVINFO_CONTENT}/metadata/pkg/{package}/mods.xml', 'application/xml'))
            transcripts = dict(captured.get('transcripts', {}))
            if html_dir:
                for url in merged['html_urls'].split(';'):
                    html = Path(html_dir) / Path(urlsplit(url).path).name
                    if url and html.is_file() and not transcripts.get(url, {}).get('retrieved_at'):
                        transcripts[url] = evidence.observation(html.read_bytes(), url, 'text/html')
            captured['transcripts'] = transcripts
            retained[package] = captured
            rows[package] = merged
            old_urls = {u for f in ('html_url', 'pdf_url', 'html_urls', 'pdf_urls') for u in (old.get(f) or '').split(';') if u}
            new_urls = {u for f in ('html_urls', 'pdf_urls') for u in merged[f].split(';') if u}
            protected = ('title', 'held_date', 'last_modified', 'hearing_dates', 'text_read',
                         'committee_code', 'committee_name', 'event_id', 'serial')
            assert all(merged.get(field) == old.get(field) for field in protected)
            receipt['packages'].append({
                'package_id': package, 'mods_sha256': captured['mods']['sha256'],
                'mods_record_change_date': root.findtext('m:recordInfo/m:recordChangeDate', '', MODS_NS),
                'csv_last_modified': old['last_modified'], 'added_urls': sorted(new_urls - old_urls),
                'changed_columns': sorted(k for k, v in merged.items() if str(old.get(k) or '') != str(v or '')),
                'cached_html_urls': sorted(transcripts),
                'scalar_disagreements_preserved': {k: {'saved': old.get(k), 'cached': parsed.get(k)}
                    for k in ('title', 'held_date', 'committee_code', 'committee_name', 'event_id')
                    if old.get(k) and parsed.get(k) and old[k] != parsed[k]},
            })
        except Exception as error:
            receipt['failures'].append({'package_id': package, 'error': str(error)})
    # HTML may have been retained independently of MODS. Associate only exact
    # filenames from reported URLs; never manufacture a content URL from an ID.
    receipt['unmatched_html_files'] = []
    if html_dir:
        urls_by_name = {}
        for package, row in rows.items():
            for url in dict.fromkeys((row.get('html_urls') or row.get('html_url') or '').split(';')):
                if url:
                    urls_by_name.setdefault(Path(urlsplit(url).path).name, []).append((package, url))
        for path in sorted(Path(html_dir).glob('*.htm')):
            matches = urls_by_name.get(path.name, [])
            if not matches:
                receipt['unmatched_html_files'].append(path.name)
            for package, url in matches:
                captured = retained.setdefault(package, {'package_id': package})
                transcripts = captured.setdefault('transcripts', {})
                if not transcripts.get(url, {}).get('retrieved_at'):
                    transcripts[url] = evidence.observation(path.read_bytes(), url, 'text/html')
    evidence.write(retained, evidence_path)
    write_csv(rows, output_path)
    receipt['output_rows'] = len(rows)
    receipt['output_sha256'] = hashlib.sha256(Path(output_path).read_bytes()).hexdigest()
    receipt['evidence_packages'] = len(retained)
    receipt['retained_mods'] = sum(bool(value.get('mods')) for value in retained.values())
    receipt['retained_html'] = sum(len(value.get('transcripts', {})) for value in retained.values())
    receipt['added_url_count'] = sum(len(p.get('added_urls', [])) for p in receipt['packages'])
    receipt['remaining_without_current_parser'] = sum(r.get('parser_version') != PARSER_VERSION for r in rows.values())
    if receipt_path:
        Path(receipt_path).parent.mkdir(parents=True, exist_ok=True)
        Path(receipt_path).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-path', type=Path, required=True)
    parser.add_argument('--mods-dir', type=Path, required=True)
    parser.add_argument('--output-path', type=Path, required=True)
    parser.add_argument('--evidence-path', type=Path, required=True)
    parser.add_argument('--html-dir', type=Path)
    parser.add_argument('--receipt-path', type=Path, required=True)
    receipt = replay(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('packages', 'failures', 'unmatched_cache_files')}))
    if receipt['failures']:
        raise SystemExit(f"{len(receipt['failures'])} GPO cache inputs failed; see receipt")


if __name__ == '__main__':
    main()

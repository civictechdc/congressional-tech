"""Regenerate indices, linked enums and the two derived schemas from guide.json.

Run from any working directory: python /path/to/tools/build.py [--check]
No original source documents or network requests are involved.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from house_naming import __version__
from house_naming.catalog import check_catalog
from house_naming.compiler import filename_schema, records_schema
from house_naming.io import loads, dumps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail on stale generated data; do not write')
    args = parser.parse_args()
    data = ROOT / 'src/house_naming/data'
    guide = loads((data / 'guide.json').read_bytes())
    if guide['catalog_version'] != __version__:
        raise SystemExit('Catalog and package version disagree')

    code_index: dict[str, list[str]] = {}
    for context, entries in guide['codes'].items():
        for token in entries:
            code_index.setdefault(token, []).append(context)
    guide['code_index'] = {k: sorted(v) for k, v in sorted(code_index.items())}
    example_index: dict[str, list[str]] = {}
    for eid, example in guide['examples'].items():
        example_index.setdefault(example['value'], []).append(eid)
    guide['example_index'] = example_index

    for typ, context, printed in [
        ('legislativeStage', 'version', False), ('measureTypeLower', 'measure', False),
        ('measureTypePrinted', 'measure', True), ('meetingType', 'meeting', True),
        ('appropriationStage', 'appropriation', True),
    ]:
        guide['field_types'][typ]['enum'] = [entry['printed'] if printed else token
                                             for token, entry in guide['codes'][context].items()]
    types = guide['field_types']
    types['untypedLegislativeStage']['enum'] = [*types['legislativeStage']['enum'], 'pih']
    # Embedded references reuse the same field definitions as primary metadata.
    for branch in types['references']['items']['oneOf']:
        for field, typ in [('measureType', 'measureTypeLower'), ('measureNumber', 'positiveInteger'), ('year', 'fiscalYear')]:
            if field in branch['properties']:
                branch['properties'][field] = deepcopy(types[typ])
    check_catalog(guide)
    outputs = {
        data / 'guide.json': dumps(guide),
        data / 'record.schema.json': dumps(records_schema(guide)),
        data / 'filename-lexical.schema.json': dumps(filename_schema(guide)),
    }
    for path, text in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != text:
                raise SystemExit(f'Out-of-date generated artifact: {path.relative_to(ROOT)}')
        else:
            path.write_text(text, encoding='utf-8')
    print(f'{"Verified" if args.check else "Wrote"} {len(outputs)} JSON artifacts')


if __name__ == '__main__':
    main()

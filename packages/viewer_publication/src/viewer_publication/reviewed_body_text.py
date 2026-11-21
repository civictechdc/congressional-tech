"""Install a selection's reviewed PDF reading through the ordinary body-text writer."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from congress_api.lake import body_text
from congress_api.lake.tables import resolve_tables, table_input
from congress_api.retention.provenance import durable_json, file_pin, run_job


def apply_reviewed_rows(*, selection_path, accepted, engine, work, tables, catalog_root=None):
    directory = Path(selection_path).parent
    manifest = directory / 'reviewed-rows.json'
    if not manifest.is_file():
        return
    review = json.loads(manifest.read_text())
    choice = {key: review[key] for key in ('body_sha256', 'parser', 'parser_version', 'text_sha256')}
    choice['status'] = 'completed'
    if (choice['parser'] != 'pdf_text' or choice not in accepted['overrides']
            or not re.fullmatch('[0-9a-f]{64}', review['prior_version'])
            or review['prior_version'] == choice['parser_version']):
        raise ValueError('Reviewed PDF reading does not match the accepted page selection')
    prior, revised = review['prior_version'], choice['parser_version']
    expected = {prior: (review['prior_text_sha256'], review['prior_text_bytes']),
                revised: (choice['text_sha256'], review['text_bytes'])}
    where = (f"body_sha=decode('{choice['body_sha256']}','hex') AND parser='pdf_text' "
             f"AND parser_version IN ('{prior}','{revised}')")

    def reviewed_file(name):
        path = directory / (name + '.parquet')
        if file_pin(path) != review['files'][name] or pq.read_metadata(path).num_rows != 1:
            raise ValueError(f'Reviewed {name} file differs from the qualified single row')
        return path

    text_file = reviewed_file('body_text')
    reviewed_pages = pq.read_table(text_file, columns=['page_offsets', 'ocr_pages']).to_pylist()[0]

    def stored_versions(phase):
        pins = resolve_tables(engine=engine, work=work / phase / 'pins', catalog_root=catalog_root, tables=tables)
        rows = run_job(work / phase / 'read', engine, inputs=[table_input(name, pin) for name, pin in pins.items()],
            steps=[], outputs=[], queries=[
                dict(name='body_text', sql=f"SELECT parser_version,encode(text_sha256,'hex') AS declared,"
                     f"encode(sha256(text),'hex') AS actual,page_offsets,ocr_pages FROM body_text WHERE {where}"),
                dict(name='readings', sql=f"SELECT parser_version,status,text_bytes FROM readings WHERE {where}")])
        versions = {}
        for name, records in rows.items():
            versions[name] = {r['parser_version'] for r in records}
            if prior not in versions[name] or len(versions[name]) != len(records):
                raise ValueError(f'Expected one retained base row per version in {name}')
            for row in records:
                digest, size = expected[row['parser_version']]
                if name == 'body_text':
                    if row['parser_version'] == revised and any(
                        row[key] != value for key, value in reviewed_pages.items()
                    ):
                        raise ValueError('Retained PDF page metadata differs from the reviewed PDF reading')
                    valid = row['declared'] == row['actual'] == digest
                else:
                    valid = row['status'] == 'completed' and row['text_bytes'] == size
                if not valid:
                    raise ValueError(f'Retained {name} differs from the reviewed PDF reading')
        return versions

    recorded = stored_versions('before')
    missing = [name for name in ('body_text', 'readings') if revised not in recorded[name]]
    if not missing:
        return
    staged = {'versions': {'pdf_text': revised}}
    for name, path in (('body_text', text_file), ('readings', reviewed_file('readings'))):
        row = pq.read_table(path).to_pylist()[0]
        if (row['body_sha'].hex(), row['parser'], row['parser_version']) != (choice['body_sha256'], 'pdf_text', revised):
            raise ValueError(f'Reviewed {name} key differs from the selected PDF')
        if name == 'body_text':
            data = row['text'].encode()
            valid = (sha256(data).hexdigest() == row['text_sha256'].hex() == choice['text_sha256']
                     and len(data) == review['text_bytes'])
        else:
            valid = row['status'] == 'completed' and row['text_bytes'] == review['text_bytes']
        if not valid:
            raise ValueError(f'Reviewed {name} differs from the selected text')
        staged[name] = path
        staged[name + '_rows'] = int(name in missing)
    result = body_text.append(staged, engine=engine, work=work / 'append', catalog_root=catalog_root, tables=tables)
    if any(revised not in versions for versions in stored_versions('after').values()):
        raise ValueError('Reviewed PDF reading is incomplete after append')
    durable_json(work / 'applied.json', result)

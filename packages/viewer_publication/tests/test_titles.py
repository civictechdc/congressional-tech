"""The title step (model/sql/titles.sql) keeps every rule the model applied before stage 1 of the title design,
in one place, and names the candidate that won (title_source)."""
import json
import os
from pathlib import Path

import pytest
from docspec_client.client import NativeDatasets
from congress_api.retention.provenance import json_input, run_job

ROOT = Path(__file__).parents[3]


def test_titles_keep_each_rule_and_name_the_winning_candidate(tmp_path):
    def doc(component, own=None, own_source='page_title', link=None, filename='file.pdf'):
        return dict(doc_key='doc:' + component, component=component, filename=filename, own_title=own,
                    own_title_source=own if own is None else own_source, link_title=link)
    docs = [doc('own', own='Hearing on Rural Lands', link='Committee link'),
            doc('heading', own='Opening Statement of Chairman Smith', own_source='page_heading'),
            doc('label_then_link', own='Testimony', link='Statement of Dr. Lee'),
            doc('label_witness', own='Biography'),
            doc('label_named_file', own='Prepared Statement'),
            doc('label_no_file', own='Testimony', filename=''),
            doc('official'), doc('formats'), doc('both'), doc('edition'), doc('rendition_label'),
            doc('copy'), doc('copy_label', link='Witness Testimony'),
            doc('corrected', own='Hearing as listed')]
    def saved(component, source_id, body, rank, fmt='pdf'):
        return dict(component=component, source_id=source_id, body_sha=body * 64, format=fmt, saved_rank=rank)
    # ct-h8dr: the first other-format file's page title, else the link text of another copy of the saved bytes, in
    # saved-file order; text on a link to other bytes of the same format titles nothing.
    files = [saved('official', 'house', '1', 1), saved('official', 'site', '1', 2), saved('official', 'mirror', '1', 3),
             saved('formats', 'pdf', '3', 1), saved('formats', 'html', '4', 2, 'html'),
             saved('both', 'chrg', '5', 1), saved('both', 'transcript', '5', 2), saved('both', 'htm', '6', 3, 'html'),
             saved('edition', 'new', '7', 1), saved('edition', 'old', '8', 2),
             saved('rendition_label', 'r1', '9', 1), saved('rendition_label', 'r2', 'a', 2, 'html'), saved('rendition_label', 'r3', 'b', 3, 'xml')]
    readings = dict(site=(None, 'Mr. Steve Mathison'), mirror=(None, 'Mathison testimony'), html=('H.R. 5376', None),
                    transcript=(None, 'GPO_FINAL_5.19.21.pdf (10.25 MB)'), htm=('- HEARING ON PENDING NOMINATIONS', None),
                    old=(None, 'An earlier edition'), r2=('Testimony', None), r3=('Named only by a later file', None))
    annotations = [dict(source_id=s, reading_title=r, reading_source=None if r is None else 'page_title', listing_title=l)
                   for s, (r, l) in readings.items()]
    rules = json.loads((ROOT / 'model/registries/title-rules.json').read_text())
    inputs = [
        json_input(tmp_path, 'base_normalized', docs, doc_key='Utf8', component='Utf8', filename='Utf8', own_title='Utf8',
                   own_title_source='Utf8', link_title='Utf8'),
        json_input(tmp_path, 'saved_files', files, component='Utf8', source_id='Utf8', body_sha='Utf8', format='Utf8', saved_rank='Int64'),
        json_input(tmp_path, 'source_annotations', annotations, source_id='Utf8', reading_title='Utf8', reading_source='Utf8', listing_title='Utf8'),
        json_input(tmp_path, 'recovered_copy_fills', [dict(component='copy', title='Recovered copy title'), dict(component='copy_label', title='Biography')],
                   component='Utf8', title='Utf8'),
        json_input(tmp_path, 'document_witness_keys', [dict(component='label_witness', witness_name='Hon. Jane Doe'),
                   dict(component='own', witness_name='Hon. Jane Doe'), dict(component='copy_label', witness_name='Ms. Ada Park')],
                   component='Utf8', witness_name='Utf8'),
        json_input(tmp_path, 'document_link_keys', [dict(component='corrected', link_key='a' * 16)], component='Utf8', link_key='Utf8'),
        json_input(tmp_path, 'title_overrides', [dict(link_key='a' * 16, title='Hearing on Rural Lands, Part 2',
                   replaces='Hearing as listed', evidence='planted')], link_key='Utf8', title='Utf8', replaces='Utf8', evidence='Utf8'),
        json_input(tmp_path, 'title_rules', [dict(id=r['id'], kind=r['kind'], pattern=r['pattern']) for r in rules],
                   id='Utf8', kind='Utf8', pattern='Utf8')]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs,
        steps=[dict(name='titles', sql=(ROOT / 'model/sql/titles.sql').read_text(), materialize=True)], outputs=[],
        queries=[dict(name='titles', sql='SELECT doc_key,title,title_source FROM titles ORDER BY doc_key')])
    got = {row['doc_key'][4:]: (row['title'], row['title_source']) for row in result['titles']}
    assert got == {
        'own': ('Hearing on Rural Lands', 'page_title'),                       # a named title ignores the witness
        'heading': ('Opening Statement of Chairman Smith', 'page_heading'),
        'label_then_link': ('Statement of Dr. Lee', 'link_text'),             # ct-ccsi: a label alone names nothing
        'label_witness': ('Biography - Hon. Jane Doe', 'label_witness'),      # the recovery copy lacked bare "biography"
        'label_no_file': ('Testimony', 'page_title'),                         # kept only with no filename to show
        'official': ('Mr. Steve Mathison', 'copy_link_text'),
        'formats': ('H.R. 5376', 'other_format_page_title'),
        'both': ('- HEARING ON PENDING NOMINATIONS', 'other_format_page_title'),
        'copy': ('Recovered copy title', 'recovered_copy'),
        'copy_label': ('Witness Testimony - Ms. Ada Park', 'label_witness'),  # the first label takes the name
        'corrected': ('Hearing on Rural Lands, Part 2', 'correction')}
    # label_named_file: the filename shows instead. edition: other bytes of one format title nothing.
    # rendition_label: the first other-format title is a label, so the later file's title is not read.


def test_a_title_correction_names_its_key_title_replaced_title_and_evidence():
    from viewer_publication.archive_model import _validate_title_overrides
    good = dict(link_key='a' * 16, title='Hearing on Rural Lands', replaces='Hearing as listed', evidence='review 2026-11-11')
    _validate_title_overrides([good, dict(good, link_key='b' * 16, replaces=None)])
    for bad in ([good, good], [dict(good, link_key='A' * 16)], [dict(good, title=' padded')], [dict(good, evidence='')],
                [{k: v for k, v in good.items() if k != 'replaces'}]):
        with pytest.raises(ValueError, match='title override'):
            _validate_title_overrides(bad)

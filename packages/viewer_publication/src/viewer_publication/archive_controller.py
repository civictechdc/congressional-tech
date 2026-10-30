"""Bind actual native model evidence to the one guarded publication controller."""
import json
import os
import re
from pathlib import Path
from time import perf_counter

from congress_api.retention.provenance import file_pin,run_job
from viewer_publication.archive_model import (
    prepare_model_inputs,build_prepared_release,admission_checks,input_receipts_query,
)
from viewer_publication.archive_model_job import (
    model_arguments,provenance_record_kind,provenance_etag_md5,PROVENANCE,
)
from viewer_publication.archive_publish import (
    NativeArchiveStore,input_digest,matching_live_input,publish_candidate,read_pointer,write_status,
)
from viewer_publication.receipt_pins import receipt_list


def _publication_directory(path,*,fresh):
    """Persist each newly created directory name before publication can start."""
    target=Path(path).resolve();missing=[];current=target
    while not current.exists():
        missing.append(current.parent);current=current.parent
    target.mkdir(parents=True,exist_ok=not fresh)
    for parent in missing:
        descriptor=os.open(parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    return target


def _reports(result):
    reports={}
    for query in result['queries']:
        if query['name'] in reports:raise ValueError('Duplicate native publication evidence')
        reports[query['name']]=query['data']
    return reports


def _admitted(reports,names):
    for name in names:
        rows=reports.get(name)
        if (not isinstance(rows,list) or len(rows)!=1 or not rows[0]
                or any(type(value) is not int or value!=0 for value in rows[0].values())):
            raise ValueError('Publication admission refused: '+name)


def _receipt_evidence(reports,expected):
    rows=reports.get('input_receipts')
    if (not isinstance(rows,list) or any(not isinstance(row,dict) or set(row)!={'receipt_key'} for row in rows)
            or [row['receipt_key'] for row in rows]!=expected):
        raise ValueError('Publication receipt identity differs from actual native model inputs')


def _provenance_snapshot(client,bucket,expected):
    """Confirm the complete immutable raw set with one metadata listing, no GETs."""
    pinned={item['key']:item['etag'] for item in expected}
    actual={};token=None
    while True:
        request=dict(Bucket=bucket,Prefix='provenance/')
        if token is not None:request['ContinuationToken']=token
        page=client.list_objects_v2(**request)
        for item in page.get('Contents',[]):
            key,etag=item['Key'],item['ETag']
            if (not isinstance(key,str) or not key.startswith('provenance/') or key in actual
                    or not isinstance(etag,str) or not etag.strip()):
                raise ValueError('Invalid current provenance inventory')
            actual[key]=etag
        if not page.get('IsTruncated'):break
        next_token=page.get('NextContinuationToken')
        if not next_token or next_token==token:raise ValueError('Current provenance listing did not advance')
        token=next_token
    def same_etag(key):
        if provenance_record_kind(key) is not None:
            return provenance_etag_md5(actual[key])==provenance_etag_md5(pinned[key])
        return actual[key]==pinned[key]
    if set(actual)!=set(pinned) or any(not same_etag(key) for key in actual):
        raise ValueError('Pinned provenance differs from the current immutable raw inventory')
    return [dict(key=key,etag=actual[key]) for key in sorted(actual)]


def _probe_evidence(reports):
    rows=reports.get('probe_selectors')
    if (not isinstance(rows,list) or len(rows)!=1 or set(rows[0])!={'saved_row','link_key'}
            or type(rows[0]['saved_row']) is not int or rows[0]['saved_row']<0
            or not isinstance(rows[0]['link_key'],str) or re.fullmatch('[a-f0-9]{16}',rows[0]['link_key']) is None):
        raise ValueError('Native model supplied no visible saved-document probe selectors')
    return rows[0]


def run_publish(model_spec,*,client,engine,bucket,work,receipt_keys,provenance,run,
                public_origin,contract,canary,verified_files=None,measured_release_id=None,comparison_acceptance=None):
    """Prepare once, admit before a skip, otherwise export once and publish.

    SQL, graphs, grouping and file writing use the maintained native model.
    Only external SDK, native runtime and site probes are supplied by startup.
    Receipt/provenance metadata identifies the prospective inputs; native results
    prove their actual receipt population before any release or input-record PUT.
    """
    from viewer_publication.archive_comparison_acceptance import require_comparison
    require_comparison(comparison_acceptance,captures=model_spec['captures'])
    receipt_keys=list(receipt_keys);receipt_list(receipt_keys);provenance=list(provenance)
    keys=sorted(set(receipt_keys))
    if not isinstance(run,dict) or not run:raise ValueError('Publication requires explicit run metadata')
    pinned={item['key'] for item in provenance}
    records={key for key in pinned if provenance_record_kind(key) is not None}
    selected=[item['key'] for name in PROVENANCE for item in model_spec[name]]
    if len(selected)!=len(set(selected)) or set(selected)!=records:
        raise ValueError('Publication provenance records must equal the actual model input set')
    work=_publication_directory(work,fresh=True)
    status=dict(status='failed',input_digest=None,live_release=None,live_release_basis='unknown',rows={},bytes=0)
    started=perf_counter();delegate=False;storage_ready=False;failure=None
    try:
        with model_arguments(model_spec,provenance_etags={item['key']:item['etag'] for item in provenance if item['key'] in records},
                             verified_files=verified_files) as arguments:
            engine.verify_runtime()
            storage_ready=True
            provenance=_provenance_snapshot(client,bucket,provenance)
            pointer,etag=read_pointer(client,bucket=bucket,evidence=work/'outgoing-pointer.json')
            status.update(live_release=pointer['release_id'] if pointer else None,live_release_basis='pinned_at_start')
            prepared=prepare_model_inputs(**arguments,parser_versions=model_spec['parser_versions'],
                catalog_version=model_spec['catalog_version'],engine=engine,scratch=model_spec['scratch'])
            profile=prepared['profile']
            entity_digests=prepared.get('entity_digests') or {}
            digest=input_digest(receipt_keys=keys,provenance=provenance,profile=profile['profile'],entity_digests=entity_digests)
            status['input_digest']=digest
            live_input=None
            if pointer:
                lookup=NativeArchiveStore(client=client,engine=engine,bucket=bucket,work=work/'input-lookup')
                live_input=matching_live_input(lookup,release_id=pointer['release_id'],digest=digest)
            if live_input is not None:
                admission=prepared['scratch']/'admission';admission.mkdir()
                checks=admission_checks(parser_versions=prepared['parser_versions'],catalog_version=prepared['catalog_version'])
                reports=run_job(admission,engine,inputs=prepared['inputs'],steps=prepared['steps'],outputs=[],
                    queries=checks+[input_receipts_query()])
                _admitted(reports,[query['name'] for query in checks]);_receipt_evidence(reports,keys)
                manifest=None
            else:
                manifest=build_prepared_release(prepared,engine=engine,output=model_spec['output'])
                result=json.loads((prepared['scratch']/'result.json').read_text())
                reports=_reports(result)
                _admitted(reports,['invariants','model_invariants','url_state_invariants','profile_completeness'])
                _receipt_evidence(reports,keys)
                probe_selectors=_probe_evidence(reports)
        # Local custody must still hold after native consumption and before any
        # successful status, reader probe, release upload or input-record write.
        require_comparison(comparison_acceptance,captures=model_spec['captures'])
        if manifest is None:
            if measured_release_id is not None and measured_release_id!=pointer['release_id']:
                raise ValueError('Measured site targets identify a different release')
            status.update(status='input_unchanged',release_id=pointer['release_id'])
            return dict(status)
        record=dict(input_digest=digest,profile=profile['profile'],snapshots=profile['snapshots'],
            provenance=provenance,entity_digests=entity_digests,run=run)
        pin=lambda path:dict(path=str(path),**file_pin(path))
        artifacts=dict(manifest_pin=pin(Path(model_spec['output'])/'manifest.json'),
            result_pin=pin(prepared['scratch']/'result.json'))
        delegate=True
        return publish_candidate(client=client,engine=engine,bucket=bucket,work=work/'candidate',
            release=Path(model_spec['output']),**artifacts,input_record=record,receipt_keys=keys,
            measured_release_id=measured_release_id,comparison_acceptance=comparison_acceptance,
            pointer=pointer,expected_etag=etag,public_origin=public_origin,
            contract=lambda **context:contract(**context,probe_selectors=probe_selectors),
            canary=lambda **context:canary(**context,probe_selectors=probe_selectors))
    except BaseException as error:
        failure=error;status['error_type']=type(error).__name__
        raise
    finally:
        if storage_ready and not delegate:
            status['durations']={'total':perf_counter()-started}
            try:write_status(client,bucket=bucket,status=status,comparison_acceptance=comparison_acceptance)
            except BaseException:
                if failure is None:raise
                failure.add_note('Archive status update also failed')


"""Bind actual native model evidence to the one guarded publication controller."""
import json
from pathlib import Path
from time import perf_counter

from congress_api.retention.provenance import file_pin,run_job
from viewer_publication.archive_model import (
    prepare_model_inputs,build_prepared_release,admission_checks,input_receipts_query,
)
from viewer_publication.archive_model_job import model_arguments,PROVENANCE
from viewer_publication.archive_publish import (
    NativeArchiveStore,input_digest,matching_live_input,publish_candidate,read_pointer,write_status,
)
from viewer_publication.receipt_pins import receipt_list


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


def run_publish(model_spec,*,client,engine,bucket,work,receipt_keys,provenance,run,
                public_origin,contract,canary):
    """Prepare once, admit before a skip, otherwise export once and publish.

    SQL, graphs, grouping and file writing use the maintained native model.
    Only external SDK, native runtime and site probes are supplied by startup.
    Receipt/provenance metadata identifies the prospective inputs; native results
    prove their actual receipt population before any release or input-record PUT.
    """
    receipt_keys=list(receipt_keys);receipt_list(receipt_keys);provenance=list(provenance)
    keys=sorted(set(receipt_keys))
    if not isinstance(run,dict) or not run:raise ValueError('Publication requires explicit run metadata')
    pinned={item['key'] for item in provenance}
    selected={item['key'] for name in PROVENANCE for item in model_spec[name]}
    if not selected<=pinned:raise ValueError('Publication provenance set omits a model input')
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    status=dict(status='failed',input_digest=None,live_release=None,live_release_basis='unknown',rows={},bytes=0)
    started=perf_counter();delegate=False;storage_ready=False;failure=None
    try:
        with model_arguments(model_spec) as arguments:
            engine.verify_runtime()
            storage_ready=True
            pointer,etag=read_pointer(client,bucket=bucket)
            status.update(live_release=pointer['release_id'] if pointer else None,live_release_basis='pinned_at_start')
            prepared=prepare_model_inputs(**arguments,parser_versions=model_spec['parser_versions'],
                catalog_version=model_spec['catalog_version'],engine=engine,scratch=model_spec['scratch'])
            profile=prepared['profile']
            digest=input_digest(receipt_keys=keys,provenance=provenance,profile=profile['profile'],entity_digests={})
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
        # Local custody must still hold after native consumption and before any
        # successful status, reader probe, release upload or input-record write.
        if manifest is None:
            status.update(status='input_unchanged',release_id=pointer['release_id'])
            return dict(status)
        record=dict(input_digest=digest,profile=profile['profile'],snapshots=profile['snapshots'],
            provenance=provenance,entity_digests={},run=run)
        pin=lambda path:dict(path=str(path),**file_pin(path))
        delegate=True
        return publish_candidate(client=client,engine=engine,bucket=bucket,work=work/'candidate',
            release=Path(model_spec['output']),manifest_pin=pin(Path(model_spec['output'])/'manifest.json'),
            result_pin=pin(prepared['scratch']/'result.json'),input_record=record,receipt_keys=keys,
            pointer=pointer,expected_etag=etag,public_origin=public_origin,contract=contract,canary=canary)
    except BaseException as error:
        failure=error;status['error_type']=type(error).__name__
        raise
    finally:
        if storage_ready and not delegate:
            status['durations']={'total':perf_counter()-started}
            try:write_status(client,bucket=bucket,status=status)
            except BaseException:
                if failure is None:raise
                failure.add_note('Archive status update also failed')

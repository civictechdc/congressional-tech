"""Bind actual native model evidence to the one guarded publication controller."""
import json
import os
import re
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

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


class PublicationInputsChanged(ValueError):
    """A retained attempt belongs to different current inputs."""


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


def _continuation_digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _save_continuation(path,value,*,seal=False):
    """Make a continuation visible only after its complete bytes are durable."""
    if seal:value=dict(value,continuation_sha256=_continuation_digest(value))
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    with temporary.open('x') as target:
        json.dump(value,target,sort_keys=True,separators=(',',':'))
        target.flush();os.fsync(target.fileno())
    os.replace(temporary,path)
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def _read_continuation(work, *, daily=False):
    """Read the existing intent or checkpoint before comparing current inputs."""
    checkpoint_path=work/'completed-model.json'
    source=checkpoint_path if checkpoint_path.exists() or checkpoint_path.is_symlink() else work/'model-intent.json'
    if not source.is_file() or source.is_symlink():
        raise ValueError('Publication continuation requires a completed model checkpoint or intent')
    try:checkpoint=json.loads(source.read_text())
    except (ValueError,OSError) as error:raise ValueError('Corrupt publication continuation') from error
    if not isinstance(checkpoint,dict):raise ValueError('Corrupt publication continuation fields')
    if daily:
        expected=checkpoint.pop('continuation_sha256',None)
        if expected!=_continuation_digest(checkpoint):
            raise ValueError('Retained nightly continuation checksum differs')
    fields={'version','identity','profile','entity_digests','admitted_names','pointer','pointer_etag'}
    if 'stage' in checkpoint:fields.add('stage')
    if source==checkpoint_path:fields|={'manifest_pin','result_pin'}
    if daily:fields|={'daily_summary_sha256','input_digest'}
    if set(checkpoint)!=fields:
        raise ValueError('Corrupt publication continuation fields')
    for key in ('identity','daily_summary_sha256','input_digest') if daily else ('identity',):
        value=checkpoint[key]
        if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
            raise ValueError('Corrupt publication continuation digest: '+key)
    if checkpoint['version']!=1:
        raise ValueError('Corrupt publication continuation version')
    return source,checkpoint


def _completed_artifacts(model_spec):
    """A manifest exists only after native export and local admission finish."""
    pins={}
    for name,path in [('manifest_pin',Path(model_spec['output'])/'manifest.json'),
                      ('result_pin',Path(model_spec['scratch'])/'result.json')]:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Publication continuation has no completed model artifact: '+name)
        with path.open('rb') as source:os.fsync(source.fileno())
        pins[name]=dict(path=str(path),**file_pin(path))
    return pins


def _stage_paths(value,*,model_spec,work):
    original={key:str(Path(model_spec[key]).resolve()) for key in ('output','scratch')}
    if value is None:return original
    if not isinstance(value,dict) or set(value)!=set(original) or any(not isinstance(v,str) for v in value.values()):
        raise ValueError('Invalid publication model stage')
    if value==original:return value
    output=Path(value['output']);scratch=Path(value['scratch'])
    parent=output.parent
    if (parent!=scratch.parent or parent.parent!=work/'model-attempts'
            or re.fullmatch('attempt-[a-f0-9]{32}',parent.name) is None
            or output.name!='release' or scratch.name!='scratch'
            or output.is_symlink() or scratch.is_symlink()):
        raise ValueError('Publication model stage escapes its owned attempt')
    return value


def _require_model_definition(saved,engine):
    from viewer_publication.archive_model_profile import _definition_hashes
    try:
        profile=saved['profile']['profile'];runtime=profile['runtime_pins']
        if profile['file_hashes']!=_definition_hashes(Path(__file__).parents[4]):
            raise PublicationInputsChanged('Model definitions changed since the retained intent')
        if (profile['engine_revision']!=engine.source_revision or
                runtime['binary_sha256']!=engine.binary_sha256 or runtime['platform']!=engine.platform or
                runtime['build_features']!=list(engine.build_features) or runtime['limits']!=json.loads(engine.limits.read_text())):
            raise PublicationInputsChanged('Native runtime changed since the retained intent')
        expected=['invariants','model_invariants','url_state_invariants','profile_completeness']
        if saved['entity_digests']:expected.append('entity_profile_completeness')
        if saved['admitted_names']!=expected:raise ValueError('Completed model admission set differs')
    except (KeyError,TypeError) as error:
        raise ValueError('Corrupt retained model definition') from error


def _reports(result):
    if not isinstance(result,dict) or not isinstance(result.get('queries'),list):
        raise ValueError('Invalid native publication evidence')
    reports={}
    for query in result['queries']:
        if not isinstance(query,dict) or not isinstance(query.get('name'),str) or 'data' not in query:
            raise ValueError('Invalid native publication query evidence')
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
        raise PublicationInputsChanged('Pinned provenance differs from the current immutable raw inventory')
    return [dict(key=key,etag=actual[key]) for key in sorted(actual)]


def _probe_evidence(reports):
    rows=reports.get('probe_selectors')
    if (not isinstance(rows,list) or len(rows)!=1 or set(rows[0])!={'saved_row','link_key'}
            or type(rows[0]['saved_row']) is not int or rows[0]['saved_row']<0
            or not isinstance(rows[0]['link_key'],str) or re.fullmatch('[a-f0-9]{16}',rows[0]['link_key']) is None):
        raise ValueError('Native model supplied no visible saved-document probe selectors')
    return rows[0]


def run_publish(model_spec,*,client,engine,bucket,work,receipt_keys,provenance,run,
                public_origin,contract,canary,verified_files=None,measured_release_id=None,comparison_acceptance=None,
                resume=False,release_causes=None,link_history=(),first_release=False,automatic_causes=False,
                daily_summary_sha256=None,check_current_daily=None):
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
    if type(resume) is not bool:raise ValueError('Publication resume must be explicit')
    daily_pin={}
    if daily_summary_sha256 is not None:
        if not isinstance(daily_summary_sha256,str) or not re.fullmatch('[a-f0-9]{64}',daily_summary_sha256):
            raise ValueError('Invalid daily summary digest')
        daily_pin['daily_summary_sha256']=daily_summary_sha256
    work=_publication_directory(work,fresh=not resume)
    identity=_continuation_digest(dict(model=model_spec,receipt_keys=keys,provenance=provenance,run=run,
        bucket=bucket,public_origin=public_origin,measured_release_id=measured_release_id))
    checkpoint_path=work/'completed-model.json'
    checkpoint=None;pending=None;promote_checkpoint=False
    stage=_stage_paths(None,model_spec=model_spec,work=work)
    intent_path=work/'model-intent.json'
    if resume:
        source,checkpoint=_read_continuation(work,daily=bool(daily_pin))
        if checkpoint.get('daily_summary_sha256')!=daily_summary_sha256:
            raise ValueError('Retained daily summary differs from the model continuation')
        if checkpoint['identity']!=identity:
            raise PublicationInputsChanged('Publication continuation inputs differ from the completed model')
        stage=_stage_paths(checkpoint.get('stage'),model_spec=model_spec,work=work)
        if source==intent_path:
            # The exporter writes its manifest last. Missing final metadata means
            # this attempt is unfinished; preserve it and start only this stage.
            if (Path(stage['output'])/'manifest.json').is_file():
                engine.verify_runtime()
                _require_model_definition(checkpoint,engine)
                from viewer_publication.archive_text_index import finish_text_index,semantic_policy
                if model_spec.get('text_index') and checkpoint['profile']['profile'].get('text_index')!=semantic_policy(model_spec['text_index']):
                    raise PublicationInputsChanged('Text preparation runtime changed since the retained intent')
                finish_text_index(model_spec,stage['output'])
                checkpoint.update(_completed_artifacts(stage));promote_checkpoint=True
            else:pending=checkpoint;checkpoint=None
    status=dict(status='failed',input_digest=None,live_release=None,live_release_basis='unknown',rows={},bytes=0)
    started=perf_counter();delegate=False;storage_ready=False;failure=None
    try:
        with model_arguments(model_spec,provenance_etags={item['key']:item['etag'] for item in provenance if item['key'] in records},
                             verified_files=verified_files,allow_existing_output=resume) as arguments:
            engine.verify_runtime()
            storage_ready=True
            if check_current_daily is None:provenance=_provenance_snapshot(client,bucket,provenance)
            # A resume reads the pointer again; it may have moved (for example after a flip), so
            # each later read keeps its own evidence beside the first rather than colliding with it.
            evidence=work/'outgoing-pointer.json'
            if evidence.exists():evidence=work/('outgoing-pointer-'+uuid4().hex+'.json')
            pointer,etag=read_pointer(client,bucket=bucket,evidence=evidence)
            status.update(live_release=pointer['release_id'] if pointer else None,live_release_basis='pinned_at_start')
            # Gates 1 and 2 read the pinned live release; the ledger also reads its link history.
            # These stay out of the input identity (data model §8.3), so a resume keeps its
            # checkpoint. Fetched only after the selected-release checks below.
            from viewer_publication.release_gate import client_reader,fetch_base
            def held_base():
                return fetch_base(lambda rid:client_reader(client,bucket,rid),
                    pointer['release_id'] if pointer else None,work,list(link_history),
                    previous_release_id=pointer.get('previous_release_id') if pointer else None)
            base_release=prior=retired=None;history=[]
            if pending is not None:
                _require_model_definition(pending,engine)
                if pointer!=pending['pointer'] or etag!=pending['pointer_etag']:
                    raise PublicationInputsChanged('Selected release changed since the retained model intent')
                attempt=_publication_directory(work/'model-attempts'/('attempt-'+uuid4().hex),fresh=True)
                _save_continuation(attempt/'prior-intent.json',pending)
                stage=dict(output=str(attempt/'release'),scratch=str(attempt/'scratch'))
            if checkpoint is None:
                base_release,prior,retired,history=held_base()
                prepared=prepare_model_inputs(**arguments,parser_versions=model_spec['parser_versions'],
                    catalog_version=model_spec['catalog_version'],engine=engine,scratch=stage['scratch'],
                    prior_links=prior,base_retired=retired)
                profile=prepared['profile']
                if model_spec.get('text_index'):
                    from viewer_publication.archive_text_index import semantic_policy
                    profile['profile']['text_index']=semantic_policy(model_spec['text_index'])
                entity_digests=prepared.get('entity_digests') or {}
            else:
                _require_model_definition(checkpoint,engine)
                profile=checkpoint['profile'];entity_digests=checkpoint['entity_digests']
                expected_paths=dict(manifest_pin=Path(stage['output'])/'manifest.json',
                                    result_pin=Path(stage['scratch'])/'result.json')
                for name in ('manifest_pin','result_pin'):
                    pin=checkpoint[name]
                    if Path(pin['path'])!=expected_paths[name] or file_pin(pin['path'])!={k:pin[k] for k in ('sha256','size')}:
                        raise ValueError('Completed model artifact changed: '+name)
                result=json.loads(Path(checkpoint['result_pin']['path']).read_text())
                reports=_reports(result)
                _admitted(reports,checkpoint['admitted_names']);_receipt_evidence(reports,keys)
                probe_selectors=_probe_evidence(reports)
            def find_live_input(digest):
                lookup=NativeArchiveStore(client=client,engine=engine,bucket=bucket,work=work/('input-lookup-'+uuid4().hex))
                return matching_live_input(lookup,release_id=pointer['release_id'],digest=digest)
            live_input=None;pointer_matches=False;selected_candidate=False
            if checkpoint is not None and pointer is not None:
                candidate=json.loads(Path(checkpoint['manifest_pin']['path']).read_text())['release_id']
                prior=checkpoint['pointer']['release_id'] if checkpoint['pointer'] else None
                pointer_matches=pointer['release_id']==candidate and pointer.get('previous_release_id')==prior
            if check_current_daily is not None:
                if pointer_matches:
                    # A committed candidate is reconciled against the immutable input record
                    # already written for it, even if new work arrived after the flip.
                    live_input=find_live_input(checkpoint['input_digest'])
                    if live_input is None:raise ValueError('Selected nightly candidate has no matching input record')
                    provenance=live_input['provenance']
                else:
                    check_current_daily()
                    provenance=_provenance_snapshot(client,bucket,provenance)
            digest=input_digest(receipt_keys=keys,provenance=provenance,profile=profile['profile'],entity_digests=entity_digests)
            status['input_digest']=digest
            if daily_pin:
                if checkpoint is not None and checkpoint['input_digest']!=digest:
                    raise ValueError('Retained nightly input identity differs from the model continuation')
                daily_pin['input_digest']=digest
            if pointer and live_input is None:live_input=find_live_input(digest)
            if checkpoint is not None:
                selected_candidate=pointer_matches and live_input is not None
                if not selected_candidate and (pointer!=checkpoint['pointer'] or etag!=checkpoint['pointer_etag']):
                    raise PublicationInputsChanged('Selected release changed since the completed model checkpoint')
            if live_input is not None and checkpoint is None:
                admission=prepared['scratch']/'admission';admission.mkdir()
                checks=admission_checks(parser_versions=prepared['parser_versions'],catalog_version=prepared['catalog_version'],
                    include_entities=bool(prepared.get('include_entities')))
                reports=run_job(admission,engine,inputs=prepared['inputs'],steps=prepared['steps'],outputs=[],
                    queries=checks+[input_receipts_query()])
                _admitted(reports,[query['name'] for query in checks]);_receipt_evidence(reports,keys)
                manifest=None
            elif checkpoint is None:
                admitted_names=['invariants','model_invariants','url_state_invariants','profile_completeness']
                if prepared.get('include_entities'):admitted_names.append('entity_profile_completeness')
                # Persist before the expensive job. A process can die after the
                # exporter finishes and before this controller regains control.
                _save_continuation(intent_path,dict(version=1,identity=identity,profile=profile,
                    entity_digests=entity_digests,admitted_names=admitted_names,pointer=pointer,pointer_etag=etag,stage=stage,
                    **daily_pin),seal=bool(daily_pin))
                manifest=build_prepared_release(prepared,engine=engine,output=stage['output'])
                if model_spec.get('text_index'):
                    from viewer_publication.archive_text_index import finish_text_index
                    manifest=finish_text_index(model_spec,stage['output'])
                result=json.loads((prepared['scratch']/'result.json').read_text())
                reports=_reports(result)
                _admitted(reports,admitted_names)
                _receipt_evidence(reports,keys)
                probe_selectors=_probe_evidence(reports)
            else:
                manifest=json.loads(Path(checkpoint['manifest_pin']['path']).read_text())
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
        candidate_id=json.loads(Path(stage['output'],'manifest.json').read_text())['release_id']
        # A resume after the flip finds its own candidate live: publish_candidate records it as
        # unchanged and runs no gate, so the old base (now superseded) is not fetched.
        if base_release is None and pointer and pointer['release_id']!=candidate_id:
            base_release,prior,retired,history=held_base()
        held=work/'base-release-record.json'
        if base_release is not None:
            record['base_release']=dict(release_id=pointer['release_id'],link_history=list(link_history),
                prior_links=file_pin(prior))
            _save_continuation(held,record['base_release'])
        elif held.is_file():
            # The published input record named this base; a resume after the flip writes it unchanged.
            record['base_release']=json.loads(held.read_text())
        if first_release:record['first_release']=True
        pin=lambda path:dict(path=str(path),**file_pin(path))
        artifacts=(dict(manifest_pin=pin(Path(stage['output'])/'manifest.json'),
            result_pin=pin(prepared['scratch']/'result.json')) if checkpoint is None else
            {name:checkpoint[name] for name in ('manifest_pin','result_pin')})
        if checkpoint is None or promote_checkpoint:
            saved=dict(version=1,identity=identity,profile=profile,entity_digests=entity_digests,
                       admitted_names=admitted_names if checkpoint is None else checkpoint['admitted_names'],
                       pointer=pointer,pointer_etag=etag,stage=stage,**artifacts,**daily_pin)
            _save_continuation(checkpoint_path,saved,seal=bool(daily_pin))
        delegate=True
        return publish_candidate(client=client,engine=engine,bucket=bucket,work=work/('candidate-'+uuid4().hex),
            release=Path(stage['output']),**artifacts,input_record=record,receipt_keys=keys,
            asset_journal=work/'publication-assets.json',
            measured_release_id=measured_release_id,comparison_acceptance=comparison_acceptance,
            pointer=pointer,expected_etag=etag,public_origin=public_origin,
            selected_pointer_reconciled=check_current_daily is not None and selected_candidate,
            base_release=base_release,release_causes=release_causes,link_history_dirs=history,first_release=first_release,
            automatic_captures=model_spec['captures'] if automatic_causes else None,
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


"""Whole-receipt scheduling for the existing captures ingest CLI.

The independent source-count report supplies costs and expected rows. Scheduling
sorts O(R log R), packs in O(R), and never moves or interprets receipt payloads.
Source parsing, guards, key anti-joins, table appends and acceptance use DocSpec.
"""
from hashlib import sha256
from datetime import datetime,timezone
import json
from pathlib import Path
import importlib.util
import errno
import os
import shutil
import signal
import subprocess
import sys
import time

from congress_api.retention.body_store import validate_key
from congress_api.retention.provenance import file_pin


CHECK_SCOPES={
    'positions':('receipt_key','receipt_line'),
    'reference_shapes':('receipt_key','receipt_line'),
    'invalid':('receipt_key','receipt_line'),
    'secondary':('receipt_key','receipt_line','body_key','body_sha'),
    'list_facts':('receipt_key','receipt_line','list_ordinal'),
    'missing':('receipt_key',),
}


def log_status(path,*,step,batch,of,receipts,rows,secs,peak_phys_gb,status,note):
    """Append the owner's small progress record; never replace earlier evidence."""
    if status not in {'running','ok','fail'}:raise ValueError('Invalid rebuild progress status')
    value=dict(ts=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        step=step,batch=batch,of=of,receipts=receipts,rows=rows,secs=secs,
        peak_phys_gb=peak_phys_gb,status=status,note=note)
    encoded=json.dumps(value,allow_nan=False,separators=(',',':'))+'\n'
    with Path(path).open('a',encoding='utf-8') as stream:stream.write(encoded)


def receipt_local_check_scopes(checks):
    """Enumerate the source guards which compose across whole receipts.

    Positions, shapes and vocabulary checks inspect one source row. Secondary
    coverage and storage joins use receipt, line and body identity. List-fact
    comparisons use receipt, line and item ordinal. Missing input checks use the
    selected receipt key. No existing predicate compares different receipts.
    An unclassified future predicate prevents starting the batch writer.
    """
    names=[check['name'] for check in checks]
    if len(names)!=len(set(names)) or set(names)!=set(CHECK_SCOPES):
        raise ValueError('Every source guard needs an explicit receipt-local scope')
    return {name:CHECK_SCOPES[name] for name in names}


def _positive(value,name):
    if type(value) is not int or value<=0:raise ValueError(name+' must be a positive integer')


def make_plan(files,counts,*,byte_target,item_target):
    """Next-fit decreasing on both independent costs; oversized receipts stand alone.

    Accepted stage files are also indivisible: their receipt keys stay together
    and are passed to the same CLI append operation without rereading raw.
    """
    _positive(byte_target,'byte_target');_positive(item_target,'item_target')
    inventory={};metrics={}
    for row in files:
        key=row.get('key')
        if not isinstance(key,str) or not key.startswith('receipts/') or key in inventory:
            raise ValueError('Inventory needs unique original receipt keys')
        validate_key(key)
        if row.get('path') is not None and row.get('prepared_stage') is not None:
            raise ValueError('A receipt needs one source backend')
        for name in ('path','prepared_stage'):
            if row.get(name) is not None and (not isinstance(row[name],str)
                    or not Path(row[name]).is_absolute() or '..' in Path(row[name]).parts):
                raise ValueError('Receipt source paths must be absolute')
        if not row.get('path') and not row.get('prepared_stage'):
            raise ValueError('Backfill source requires original receipt files or an accepted stage')
        inventory[key]=dict(row)
    fields=('source_rows','uncompressed_bytes','list_items','expected_captures',
            'max_line_bytes','max_line_items')
    for row in counts:
        key=row.get('key')
        if not isinstance(key,str):raise ValueError('Source-count keys must be strings')
        if key in metrics:raise ValueError('Duplicate source-count key')
        for name in fields:_positive(row.get(name),name)
        if (row['expected_captures']>row['list_items']
                or row['max_line_bytes']>row['uncompressed_bytes']
                or row['max_line_items']>row['list_items']):
            raise ValueError('Inconsistent independent source costs')
        metrics[key]={name:row[name] for name in fields}
    if not inventory or set(inventory)!=set(metrics):
        raise ValueError('Source counts must equal the complete pinned receipt inventory')
    units={}
    for key,row in inventory.items():
        kind='prepared-stage' if row.get('prepared_stage') else 'receipt-files'
        identity=(kind,row['prepared_stage'] if kind=='prepared-stage' else key)
        unit=units.setdefault(identity,dict(source_kind=kind,receipt_keys=[],
            uncompressed_bytes=0,list_items=0,expected_captures=0,source_rows=0))
        if kind=='prepared-stage':unit['prepared_stage']=row['prepared_stage']
        unit['receipt_keys'].append(key)
        for name in ('uncompressed_bytes','list_items','expected_captures','source_rows'):
            unit[name]+=metrics[key][name]
    def weight(unit):return max(unit['uncompressed_bytes']*item_target,unit['list_items']*byte_target)
    def order(unit):return (-weight(unit),-unit['uncompressed_bytes'],-unit['list_items'],unit['receipt_keys'])
    groups={}
    for unit in units.values():
        unit['receipt_keys'].sort();groups.setdefault(unit['source_kind'],[]).append(unit)
    batches=[]
    for kind,items in sorted(groups.items()):
        current=None
        for unit in sorted(items,key=order):
            oversized=unit['uncompressed_bytes']>byte_target or unit['list_items']>item_target
            indivisible=kind=='prepared-stage' or oversized
            if current is not None and (indivisible
                    or current['uncompressed_bytes']+unit['uncompressed_bytes']>byte_target
                    or current['list_items']+unit['list_items']>item_target):
                batches.append(current);current=None
            if indivisible:
                batches.append(dict(unit,oversized_receipt=oversized));continue
            if current is None:
                current=dict(source_kind=kind,receipt_keys=[],uncompressed_bytes=0,
                    list_items=0,expected_captures=0,source_rows=0,oversized_receipt=False)
            current['receipt_keys'].extend(unit['receipt_keys'])
            for name in ('uncompressed_bytes','list_items','expected_captures','source_rows'):
                current[name]+=unit[name]
        if current is not None:batches.append(current)
    for batch in batches:batch['receipt_keys'].sort()
    batches.sort(key=order)
    for index,batch in enumerate(batches):
        batch['ordinal']=index
        batch['id']=sha256(json.dumps(batch,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(version=1,byte_target=byte_target,item_target=item_target,
        receipt_keys=sorted(inventory),source_counts=[dict(key=key,**metrics[key]) for key in sorted(metrics)],
        expected_captures=sum(row['expected_captures'] for row in metrics.values()),batches=batches)


def check_scratch(root,*outputs,min_free_bytes=15<<30):
    """Refuse unowned local outputs and resource exhaustion before an effect."""
    root=Path(root).resolve()
    if any(not Path(path).resolve().is_relative_to(root) for path in outputs):
        raise ValueError('Owned scratch root must contain every local backfill output')
    existing=root
    while not existing.exists():existing=existing.parent
    if shutil.disk_usage(existing).free<min_free_bytes:
        raise RuntimeError('Free disk is below the backfill floor')
    total=0;pending=[root] if root.exists() else []
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):pending.append(entry.path)
                    else:total+=entry.stat(follow_symlinks=False).st_blocks*512
                except FileNotFoundError:pass
    if total>5<<30:raise RuntimeError('Owned backfill scratch exceeds 5GiB')
    return root


class _MemorySamples:
    """Tolerate two transient tree-sampling gaps, retaining the last valid peak."""
    def __init__(self,sampler):
        self.sampler=sampler
        self.consecutive_failures=0

    def sample(self,pid):
        try:
            rss=self.sampler.resident_tree(pid);physical=self.sampler.physical_tree(pid)
            if physical is None:raise RuntimeError('Missing process memory sample')
        except InterruptedError:
            raise
        except (OSError,RuntimeError,subprocess.SubprocessError) as error:
            self.consecutive_failures+=1
            if self.consecutive_failures>=3:
                raise RuntimeError('Three consecutive whole-tree memory samples failed') from error
            return None
        self.consecutive_failures=0
        return rss,physical


def _group_is_live(group):
    result=subprocess.run(['ps','-axo','pgid=,stat='],capture_output=True,text=True,check=True,timeout=5)
    return any(int(parts[0])==group and not parts[1].startswith('Z')
        for line in result.stdout.splitlines() if len(parts:=line.split())==2)


def _signal_group(group,number,send,is_live):
    try:send(group,number)
    except OSError as error:
        if error.errno in (errno.EPERM,errno.ESRCH) and not is_live(group):
            return dict(signal=number,errno=error.errno,group_exited=True)
        raise


def monitor_command(command,*,work,physical_limit=16<<30,timeout=2700,min_free_bytes=15<<30,
                    scratch_root=None):
    """Run one owned batch process and record sampled RSS/physical footprint.

    The separate process group watches this monitor too: losing the tool session
    cannot leave an unbounded batch behind. Partial evidence is written at every
    sample. This one-time backfill qualification uses macOS physical accounting;
    it makes no Linux or continuous-memory qualification claim.
    """
    if sys.platform not in {'darwin','linux'}:raise RuntimeError('Backfill memory accounting requires macOS or Linux')
    _positive(physical_limit,'physical_limit');_positive(timeout,'timeout')
    if not isinstance(command,list) or not command or any(not isinstance(v,str) for v in command):
        raise ValueError('A concrete batch command is required')
    work=Path(work)
    scratch_root=check_scratch(work if scratch_root is None else scratch_root,work,
        min_free_bytes=min_free_bytes)
    work.mkdir(parents=True,exist_ok=True)
    report=work/'measurement.json';partial=work/'measurement.json.partial';log=work/'process.log'
    if any(p.exists() for p in (report,partial,log)):raise FileExistsError('Batch measurement paths must be fresh')
    path=Path(__file__).resolve().parents[5]/'scripts/measure/process_rss.py'
    spec=importlib.util.spec_from_file_location('backfill_memory_sampler',path)
    sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
    memory=_MemorySamples(sampler)
    watchdog='''import os,signal,subprocess,sys,time
parent=int(sys.argv[1])
process=subprocess.Popen(sys.argv[2:])
while process.poll() is None:
 if os.getppid()!=parent:
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  os.killpg(os.getpgrp(),signal.SIGTERM)
  time.sleep(2)
  os.killpg(os.getpgrp(),signal.SIGKILL)
 time.sleep(.1)
raise SystemExit(process.returncode)
'''
    def interrupted(number,_frame):raise InterruptedError('Batch monitor received signal '+str(number))
    old={number:signal.getsignal(number) for number in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
    for number in old:signal.signal(number,interrupted)
    started=time.monotonic();peak=0;physical_peak=0;samples=0;failure=None;child=None;disk_next=started
    primary_error=None;cleanup_errors=[]
    try:
        with log.open('x') as output:
            child=subprocess.Popen([sys.executable,'-I','-c',watchdog,str(os.getpid()),*command],
                stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while child.poll() is None:
                    observed=memory.sample(child.pid)
                    if observed is not None:
                        rss,physical=observed
                        peak=max(peak,rss);physical_peak=max(physical_peak,physical);samples+=1
                    value=dict(status='running_unaccepted',monitor_pid=os.getpid(),owned_pgid=child.pid,
                        seconds=time.monotonic()-started,samples=samples,sampled_peak_tree_rss=peak,
                        sampled_peak_tree_physical_footprint=physical_peak,
                        consecutive_sample_failures=memory.consecutive_failures)
                    temporary=partial.with_suffix('.tmp');temporary.write_text(json.dumps(value)+'\n');temporary.replace(partial)
                    if observed is not None and physical>physical_limit:
                        raise RuntimeError('Batch exceeded its physical memory limit')
                    if shutil.disk_usage(work).free<min_free_bytes:raise RuntimeError('Free disk dropped below the backfill floor')
                    if time.monotonic()>=disk_next:
                        check_scratch(scratch_root,work,min_free_bytes=min_free_bytes)
                        disk_next=time.monotonic()+5
                    if time.monotonic()-started>timeout:raise RuntimeError('Batch exceeded its time limit')
                    time.sleep(.5)
            except Exception as error:
                primary_error=error
                failure=dict(type=type(error).__name__,message=str(error))
                if child.poll() is None:
                    try:
                        note=_signal_group(child.pid,signal.SIGTERM,os.killpg,_group_is_live)
                        if note:cleanup_errors.append(note)
                    except OSError as cleanup:cleanup_errors.append(dict(type=type(cleanup).__name__,message=str(cleanup)))
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:pass
                # The group can outlive its leader when a descendant ignores TERM.
                try:
                    note=_signal_group(child.pid,signal.SIGKILL,os.killpg,_group_is_live)
                    if note:cleanup_errors.append(note)
                except OSError as cleanup:cleanup_errors.append(dict(type=type(cleanup).__name__,message=str(cleanup)))
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:cleanup_errors.append(dict(type='TimeoutExpired',message='Owned group did not stop'))
            result=dict(returncode=child.poll(),seconds=time.monotonic()-started,
                monitor_pid=os.getpid(),owned_pgid=child.pid,samples=samples,
                sampled_peak_tree_rss=peak,sampled_peak_tree_physical_footprint=physical_peak,
                physical_limit=physical_limit,failure=failure,
                cleanup_errors=cleanup_errors,
                physical_basis='macOS charged physical footprint' if sys.platform=='darwin' else 'Linux RSS plus swap conservative proxy',
                qualification='sampled owned tree; not continuous or a Linux production bound')
            report.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        for number,handler in old.items():signal.signal(number,handler)
    if primary_error is not None:raise primary_error
    if result['returncode']!=0:raise RuntimeError('Batch exited '+str(result['returncode'])+'; see '+str(log))
    return result


def runtime_identity(engine,engine_config):
    """Bind the CLI subprocesses to the same explicit native runtime."""
    from docspec_client.client import NativeDatasets
    configured=NativeDatasets.from_config(engine_config)
    fields=('source_revision','binary_sha256','remote','limits','binary','workspace','timeout')
    if any(getattr(engine,name)!=getattr(configured,name) for name in fields):
        raise ValueError('Batch CLI configuration differs from the admitted native runtime')
    configured.verify_runtime()
    if configured.limits is None:raise ValueError('Backfill requires explicit native limits')
    limits=json.loads(configured.limits.read_text())
    for name,maximum in (('compute_threads',4),('memory_bytes',14<<30),('scratch_bytes',6<<30)):
        if type(limits.get(name)) is not int or not 0<limits[name]<=maximum:
            raise ValueError('Backfill native '+name+' exceeds the qualified runner budget')
    return dict(source_revision=engine.source_revision,binary_sha256=engine.binary_sha256,
        config=file_pin(engine_config),limits=file_pin(configured.limits))


def execute_batches(files,counts,*,engine,engine_config,work,table,catalog_root,location=None,
                    create_table=False,create_namespace=False,byte_target=256<<20,item_target=200000,
                    validated_counter=None,source_qualifications=None,scratch_root=None,
                    progress_log=None,progress_step='d1_backfill'):
    """Call the incremental CLI once per whole batch; never run downstream jobs.

    A fresh invocation replans from the pinned inputs. Each child resolves fresh
    native heads and skips committed receipt keys before source admission. No
    local journal decides which keys exist. Accepted complete-file stages use
    the same CLI append writer and retain their earlier mandatory source checks.
    """
    from congress_api.lake import captures,tables
    from congress_shared.custody import custody_identity
    if validated_counter is not None:
        raise ValueError('A historical counter is not a backfill input')
    plan=make_plan(files,counts,byte_target=byte_target,item_target=item_target)
    scopes=receipt_local_check_scopes(captures.capture_checks())
    if create_namespace and not create_table:raise ValueError('Namespace creation requires explicit table creation')
    if create_table and location is None:raise ValueError('Table creation requires an explicit fresh location')
    if (not isinstance(table,dict) or set(table)!={'namespace','name'}
            or not isinstance(table['namespace'],list) or not table['namespace']):
        raise ValueError('Backfill requires an explicit generation table')
    for name in [*table['namespace'],table['name']]:tables._identifier(name)
    tables.validate_catalog_authority(engine,catalog_root)
    runtime=runtime_identity(engine,engine_config)
    runtime_custody={str(path):custody_identity(path) for path in (Path(engine_config),engine.limits)}
    definition=captures.current_version()
    started=time.monotonic();completed_receipts=0;completed_rows=0;peak=0
    def progress(status,*,batch=0,note=''):
        if progress_log is not None:
            log_status(progress_log,step=progress_step,batch=batch,of=len(plan['batches']),
                receipts=completed_receipts,rows=completed_rows,secs=time.monotonic()-started,
                peak_phys_gb=peak/1e9,status=status,note=note)
    progress('running',note='Starting a fresh unpublished backfill invocation')
    work=Path(work).resolve()
    local_outputs=[work]
    if catalog_root is not None:
        local_outputs.append(catalog_root)
        if location is not None:local_outputs.append(location)
    scratch_root=check_scratch(scratch_root or work.parent,*local_outputs)
    work.mkdir(parents=True,exist_ok=False)
    (work/'plan.json').write_text(json.dumps(dict(plan,mapping_digest=definition,runtime=runtime),indent=2)+'\n')
    counts_path=work/'source-counts.json';counts_path.write_text(json.dumps(counts,indent=2)+'\n')
    try:
        if create_table:
            schema=json.loads((Path(__file__).resolve().parents[5]/'model/lake/captures.schema.json').read_text())
            tables.create_table(engine=engine,work=work/'create',catalog_root=catalog_root,table=table,
                schema=schema,location=location,create_namespace=create_namespace)
        else:
            pin=tables.resolve_tables(engine=engine,work=work/'preflight',catalog_root=catalog_root,tables={'captures':table})['captures']
            if catalog_root is not None:check_scratch(scratch_root,pin['metadata_location'])
    except BaseException as error:
        progress('fail',note=type(error).__name__+' during catalog preflight')
        raise
    inventory={row['key']:row for row in files};reports=[]
    result=dict(status='running',qualified_for_downstream=False,mapping_digest=definition,
        engine=runtime,plan=plan,batches=reports,receipt_local_checks=scopes)
    def unchanged():
        if captures.current_version()!=definition or any(custody_identity(path)!=identity
                for path,identity in runtime_custody.items()):
            raise ValueError('Backfill producer/runtime changed; rebuild an unpublished generation')
    measurement_work=None
    try:
        for batch in plan['batches']:
            unchanged()
            progress('running',batch=batch['ordinal']+1,note='Batch '+batch['id'])
            directory=work/('batch-'+str(batch['ordinal']).zfill(4)+'-'+batch['id'][:8]);directory.mkdir()
            selected=[inventory[key] for key in batch['receipt_keys']]
            if batch['source_kind']=='prepared-stage':selected=[dict(key=row['key']) for row in selected]
            input_path=directory/'receipts.json';input_path.write_text(json.dumps(selected,indent=2)+'\n')
            command=[sys.executable,'-I','-m','congress_api.cli.captures_ingest',
                '--receipt-inventory',str(input_path),'--engine-config',str(Path(engine_config).resolve()),
                '--work',str(directory/'stage'),'--apply','--table','.'.join([*table['namespace'],table['name']])]
            if catalog_root is not None:command+=['--catalog-root',str(Path(catalog_root).resolve())]
            kind=batch['source_kind']
            if kind=='prepared-stage':command+=['--append-stage',batch['prepared_stage']]
            else:
                if source_qualifications is not None:
                    paths={str(Path(row['path']).resolve()) for row in selected}
                    bindings={str(path):str(authority) for path,authority in source_qualifications.items()
                              if str(Path(path).resolve()) in paths}
                    qualification=directory/'qualifications.json';qualification.write_text(json.dumps(bindings)+'\n')
                    command+=['--source-qualifications',str(qualification)]
            measurement_work=directory/'monitor'
            measured=monitor_command(command,work=measurement_work,scratch_root=scratch_root or work)
            unchanged()
            outcome=None
            for line in reversed((directory/'monitor/process.log').read_text().splitlines()):
                try:value=json.loads(line)
                except json.JSONDecodeError:continue
                if isinstance(value,dict) and ('applied' in value or value.get('no_work')):outcome=value;break
            if outcome is None:raise ValueError('Capture CLI supplied no accepted batch outcome')
            completed_receipts+=len(batch['receipt_keys'])
            completed_rows+=outcome['rows']
            peak=max(peak,measured['sampled_peak_tree_physical_footprint'])
            reports.append(dict(id=batch['id'],receipt_keys=batch['receipt_keys'],outcome=outcome,
                measurement=measured,source_guard='accepted-stage-proof' if kind=='prepared-stage' else 'mandatory-capture-checks'))
            (work/'backfill.json').write_text(json.dumps(result,indent=2)+'\n')
            progress('ok',batch=batch['ordinal']+1,
                note='Batch committed or already present; rows count native stage outputs in this invocation')
        unchanged()
        acceptance=work/'acceptance';acceptance.mkdir()
        spec=acceptance/'spec.json';spec.write_text(json.dumps(dict(engine_config=str(Path(engine_config).resolve()),
            catalog_root=str(Path(catalog_root).resolve()) if catalog_root is not None else None,
            table=table,counts=str(counts_path),work=str(acceptance/'jobs'),mapping_digest=definition),indent=2)+'\n')
        measurement_work=acceptance/'monitor'
        result['acceptance_measurement']=monitor_command([sys.executable,'-I','-m',
            'congress_api.lake.capture_backfill','--validate-spec',str(spec)],work=measurement_work,scratch_root=scratch_root or work)
        accepted=json.loads((acceptance/'accepted.json').read_text())
        unchanged();result.update(status='public_guard_passed',pin=accepted['pin'],guard=accepted['guard'])
        completed_rows=accepted['guard']['rows']
        peak=max(peak,result['acceptance_measurement']['sampled_peak_tree_physical_footprint'])
        progress('ok',batch=len(plan['batches']),note='Whole-generation public guard passed; downstream acceptance remains pending')
        return result
    except BaseException as error:
        result.update(status='rejected',error_type=type(error).__name__)
        if measurement_work is not None:
            for name in ('measurement.json','measurement.json.partial'):
                try:
                    measured=json.loads((measurement_work/name).read_text())
                    observed=measured.get('sampled_peak_tree_physical_footprint')
                    if type(observed) is int and observed>=0:peak=max(peak,observed)
                except (OSError,ValueError):continue
        progress('fail',batch=len(reports)+1,note=type(error).__name__+'; see '+str(work/'backfill.json'))
        raise
    finally:
        (work/'backfill.json').write_text(json.dumps(result,indent=2)+'\n')


def validate_spec(path):
    """Read-only whole-generation validation in its separately measured process."""
    from docspec_client.client import NativeDatasets
    from congress_api.lake import captures,tables
    from congress_api.lake.capture_backfill_guard import validate_generation
    path=Path(path);spec=json.loads(path.read_text())
    required={'engine_config','catalog_root','table','counts','work','mapping_digest'}
    if not isinstance(spec,dict) or set(spec)!=required:raise ValueError('Invalid backfill validation spec')
    if captures.current_version()!=spec['mapping_digest']:raise ValueError('Backfill mapping changed before validation')
    engine=NativeDatasets.from_config(spec['engine_config'])
    pin=tables.resolve_tables(engine=engine,work=Path(spec['work'])/'head',catalog_root=spec['catalog_root'],
        tables={'captures':spec['table']})['captures']
    guard=validate_generation(engine=engine,work=Path(spec['work'])/'guard',pin=pin,
        counts=json.loads(Path(spec['counts']).read_text()))
    if captures.current_version()!=spec['mapping_digest']:raise ValueError('Backfill mapping changed during validation')
    result=dict(pin=pin,guard=guard,mapping_digest=spec['mapping_digest'])
    (path.parent/'accepted.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-spec',type=Path,required=True)
    args=parser.parse_args(argv)
    print(json.dumps(validate_spec(args.validate_spec),sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())

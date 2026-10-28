"""Whole-receipt scheduling for the existing captures ingest CLI.

The independent source-count report supplies costs and expected rows. Scheduling
sorts O(R log R), packs in O(R), and never moves or interprets receipt payloads.
Source parsing, guards, key anti-joins, table appends and acceptance use DocSpec.
"""
from hashlib import sha256
import json
from pathlib import Path
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import time

from congress_api.retention.body_store import validate_key


CHECK_SCOPES={
    'positions':('receipt_key','receipt_line'),
    'reference_shapes':('receipt_key','receipt_line'),
    'invalid':('receipt_key','receipt_line'),
    'secondary':('receipt_key','receipt_line','body_key','body_sha'),
    'list_facts':('receipt_key','receipt_line','list_ordinal'),
    'missing':('receipt_key',),
}


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
        kind=('prepared-stage' if row.get('prepared_stage') else
              'receipt-files' if row.get('path') else 'counter')
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


def monitor_command(command,*,work,physical_limit=16<<30,timeout=2700,min_free_bytes=15<<30):
    """Run one owned batch process and record sampled RSS/physical footprint.

    The separate process group watches this monitor too: losing the tool session
    cannot leave an unbounded batch behind. Partial evidence is written at every
    sample. This one-time backfill qualification uses macOS physical accounting;
    it makes no Linux or continuous-memory qualification claim.
    """
    if sys.platform!='darwin':raise RuntimeError('Backfill physical qualification requires macOS')
    _positive(physical_limit,'physical_limit');_positive(timeout,'timeout')
    if not isinstance(command,list) or not command or any(not isinstance(v,str) for v in command):
        raise ValueError('A concrete batch command is required')
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    report=work/'measurement.json';partial=work/'measurement.json.partial';log=work/'process.log'
    if any(p.exists() for p in (report,partial,log)):raise FileExistsError('Batch measurement paths must be fresh')
    path=Path(__file__).resolve().parents[5]/'scripts/measure/process_rss.py'
    spec=importlib.util.spec_from_file_location('backfill_memory_sampler',path)
    sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
    if shutil.disk_usage(work).free<min_free_bytes:raise RuntimeError('Free disk is below the backfill floor')
    watchdog='''import os,signal,subprocess,sys,time
parent=int(sys.argv[1])
process=subprocess.Popen(sys.argv[2:])
while process.poll() is None:
 if os.getppid()!=parent:
  os.killpg(os.getpgrp(),signal.SIGTERM)
  raise SystemExit(125)
 time.sleep(.1)
raise SystemExit(process.returncode)
'''
    def interrupted(number,_frame):raise InterruptedError('Batch monitor received signal '+str(number))
    old={number:signal.getsignal(number) for number in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
    for number in old:signal.signal(number,interrupted)
    started=time.monotonic();peak=0;physical_peak=0;samples=0;failure=None;child=None
    try:
        with log.open('x') as output:
            child=subprocess.Popen([sys.executable,'-I','-c',watchdog,str(os.getpid()),*command],
                stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while child.poll() is None:
                    rss=sampler.resident_tree(child.pid);physical=sampler.physical_tree(child.pid)
                    if physical is None:raise RuntimeError('Missing macOS physical footprint sample')
                    peak=max(peak,rss);physical_peak=max(physical_peak,physical);samples+=1
                    value=dict(status='running_unaccepted',monitor_pid=os.getpid(),owned_pgid=child.pid,
                        seconds=time.monotonic()-started,samples=samples,sampled_peak_tree_rss=peak,
                        sampled_peak_tree_physical_footprint=physical_peak)
                    temporary=partial.with_suffix('.tmp');temporary.write_text(json.dumps(value)+'\n');temporary.replace(partial)
                    if physical>physical_limit:raise RuntimeError('Batch exceeded its physical memory limit')
                    if shutil.disk_usage(work).free<min_free_bytes:raise RuntimeError('Free disk dropped below the backfill floor')
                    if time.monotonic()-started>timeout:raise RuntimeError('Batch exceeded its time limit')
                    time.sleep(.5)
            except Exception as error:
                failure=dict(type=type(error).__name__,message=str(error))
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            result=dict(returncode=child.wait(),seconds=time.monotonic()-started,
                monitor_pid=os.getpid(),owned_pgid=child.pid,samples=samples,
                sampled_peak_tree_rss=peak,sampled_peak_tree_physical_footprint=physical_peak,
                physical_limit=physical_limit,failure=failure,
                qualification='sampled owned tree; not continuous or a Linux production bound')
            report.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        for number,handler in old.items():signal.signal(number,handler)
    if failure:raise RuntimeError(failure['message'])
    if result['returncode']!=0:raise RuntimeError('Batch exited '+str(result['returncode'])+'; see '+str(log))
    return result

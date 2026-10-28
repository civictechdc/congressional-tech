"""Whole-receipt scheduling for the existing captures ingest CLI.

The independent source-count report supplies costs and expected rows. Scheduling
sorts O(R log R), packs in O(R), and never moves or interprets receipt payloads.
Source parsing, guards, key anti-joins, table appends and acceptance use DocSpec.
"""
from hashlib import sha256
import json
from pathlib import Path


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

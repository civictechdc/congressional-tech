"""Owner-selected independent receipt oracle: one C-backed event parse per line.

This measurement is explicitly outside production engine data operations. Original
JSONL gzip files are read once; only small receipt metrics and byte proofs escape.
No DuckDB, Parquet counter, raw-row export or second payload path is used.
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
from time import perf_counter

import ijson

from congress_api.lake.receipt_metadata import source_pins,recheck_source_pins
from congress_api.retention.body_store import validate_key
from congress_api.retention.raw_verifier import _HashedReader
from congress_shared.custody import custody_identity
from congress_shared.storage import single_put_md5


FIELDS=('record','captures','file_references')
REFERENCES=FIELDS[1:]


def _index(event,value):
    if event=='number' and type(value) is int:
        return value if -(1<<63)<=value<(1<<63) else None
    if event=='string' and re.fullmatch('[+-]?[0-9]+',value):
        try:number=int(value)
        except ValueError:return None
        return number if -(1<<63)<=number<(1<<63) else None
    return None


def count_line(encoded):
    """Count direct elements and reference coverage without building a JSON tree."""
    depth=0;root=False;field=None;active=None;entry=False;ref_field=None
    pointer=False;position=0;slots=[None,None];seen=set();is_list=False
    lengths=dict.fromkeys(FIELDS,0);indices={k:set() for k in REFERENCES};fallbacks=Counter()
    def finish(name,values):
        chosen=next((v for v in values if v is not None),None)
        if chosen is None:chosen=0;fallbacks[name]+=1
        indices[name].add(chosen)
    for event,value in ijson.basic_parse(encoded):
        if not root:
            if event!='start_map':raise ValueError('Malformed source JSON object')
            root=True;depth=1;continue
        if event=='map_key':
            if depth==1:field=value
            elif depth==3 and entry:ref_field=value
            continue
        if event in {'end_map','end_array'}:
            if pointer and depth==4:pointer=False
            if entry and depth==3:
                finish(active,slots);entry=False;pointer=False
            if active and depth==2:active=None
            depth-=1
            continue
        if depth==1 and field in FIELDS:
            if field in seen:raise ValueError('Malformed duplicate source field')
            seen.add(field)
            if field in REFERENCES and event not in {'start_array','null'}:
                raise ValueError('Malformed reference list')
            if event=='start_array':active=field
            if field=='record':is_list=event=='start_array'
        if active and depth==2:
            lengths[active]+=1
            if active in REFERENCES:
                slots=[None,None];ref_field=None
                if event in {'start_map','start_array'}:entry=True
                else:finish(active,slots)
        if entry and depth==3 and ref_field=='pointer' and event=='start_array':
            pointer=True;position=0
        elif pointer and depth==4:
            if position<2:slots[position]=_index(event,value)
            position+=1
        if event in {'start_map','start_array'}:depth+=1
    if not root or depth:raise ValueError('Malformed source JSON object')
    records=lengths['record'];caps=lengths['captures'];refs=lengths['file_references']
    selected='captures' if caps else 'file_references' if refs else None
    primary=lengths[selected] if selected else max(records,1)
    covered=sum(0<=i<records for i in indices[selected]) if selected else 0
    expected=primary+(records-covered if selected else 0)
    transient=primary+(records if selected else 0)+(refs if caps else 0)
    shapes=dict(record_list_lines=int(is_list),non_list_record_lines=int(not is_list),
        captures_only_lines=int(caps>0 and refs==0),references_only_lines=int(refs>0 and caps==0),
        empty_reference_list_lines=int(not caps and not refs and bool(seen.intersection(REFERENCES))))
    anomalies=dict(pointer_fallbacks=fallbacks[selected] if selected and is_list else 0,
        out_of_bounds_pointer_values=sum(not 0<=i<records for i in indices[selected]) if selected and is_list else 0)
    return expected,transient,shapes,anomalies


def _write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def count_sources(*,files,receipt_keys,work,source_qualifications=None):
    """Accept the exact original inventory after single-read byte and count checks."""
    if ijson.backend!='yajl2_c':raise ValueError('Independent counts require the locked ijson C backend')
    keys=list(receipt_keys)
    if not keys or len(keys)!=len(set(keys)):
        raise ValueError('Receipt inventory requires unique original keys')
    for key in keys:
        validate_key(key)
        if not key.startswith('receipts/'):raise ValueError('Receipt inventory has a non-receipt key')
    selected=[];identities={}
    for source in files:
        row=dict(source);row['key']=row.get('key',row.get('receipt_key'))
        if (not isinstance(row.get('path'),str) or not Path(row['path']).is_absolute()
                or '..' in Path(row['path']).parts or type(row.get('size')) is not int or row['size']<0):
            raise ValueError('Invalid original receipt metadata')
        if not isinstance(row.get('etag'),str) or not row['etag'].strip():
            raise ValueError('Invalid original receipt ETag')
        try:expected_md5=single_put_md5(row['etag'])
        except ValueError:expected_md5=None
        if row.get('md5') is not None:
            supplied=single_put_md5(row['md5'])
            if expected_md5 is not None and supplied!=expected_md5:
                raise ValueError('Receipt checksum qualification contradicts its inventory')
            expected_md5=supplied
        row['_md5']=expected_md5
        row['path']=str(Path(row['path']).absolute())
        identities[row['path']]=custody_identity(row['path'])
        if identities[row['path']][2]!=row['size']:raise ValueError('Receipt size differs from inventory')
        if 'rows' in row and (type(row['rows']) is not int or row['rows']<0):
            raise ValueError('Invalid qualified source row count')
        selected.append(row)
    if (len(selected)!=len(keys) or {r['key'] for r in selected}!=set(keys)
            or len(identities)!=len(selected)):
        raise ValueError('Receipt files must exactly match the complete unique inventory')
    bindings={str(k):str(v) for k,v in (source_qualifications or {}).items()}
    if set(bindings)-identities.keys():raise ValueError('Unexpected source qualification binding')
    qualified=[r for r in selected if r['path'] in bindings]
    pins=source_pins(files=qualified,qualifications=bindings) if qualified else []
    by_path={p['path']:p for p in pins}
    if any(r['_md5'] is None and str(Path(r['path']).resolve()) not in by_path for r in selected):
        raise ValueError('Opaque receipt ETag requires an independent byte qualification')
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    started=perf_counter();result=[];proofs=[];details=[];parsed=0;last_progress=0
    _write(work/'progress.json',dict(receipts=0,of=len(keys),source_rows=0,rows=0,secs=0))
    try:
        for source in sorted(selected,key=lambda r:r['key']):
            path=source['path'];rows=byte_count=items=captures=max_bytes=max_items=0
            shapes=Counter();anomalies=Counter()
            with Path(path).open('rb') as raw:
                hashed=_HashedReader(raw)
                with gzip.GzipFile(fileobj=hashed,mode='rb') as decoded:
                    for encoded in decoded:
                        count,weight,line_shapes,line_anomalies=count_line(encoded)
                        size=len(encoded)-(1 if encoded.endswith(b'\n') else 0)
                        if size and encoded[size-1]==13:size-=1
                        rows+=1;parsed+=1;byte_count+=size;items+=weight;captures+=count
                        max_bytes=max(max_bytes,size);max_items=max(max_items,weight)
                        shapes.update(line_shapes);anomalies.update(line_anomalies)
                        del encoded
            if custody_identity(path)!=identities[path]:raise ValueError('Receipt changed during source count')
            if hashed.size!=source['size'] or (source['_md5'] is not None and hashed.md5.hexdigest()!=source['_md5']):
                raise ValueError('Receipt compressed MD5 checksum differs from inventory')
            pin=by_path.get(str(Path(path).resolve()))
            if pin and hashed.sha.hexdigest()!=pin['sha256']:
                raise ValueError('Receipt checksum differs from its source qualification')
            expected_rows=source.get('rows',pin['qualification'].get('rows') if pin else None)
            if not rows or expected_rows is not None and rows!=expected_rows:
                raise ValueError('Receipt source rows differ from qualified creation counts')
            result.append(dict(key=source['key'],source_rows=rows,uncompressed_bytes=byte_count,
                list_items=items,expected_captures=captures,max_line_bytes=max_bytes,max_line_items=max_items))
            proofs.append(dict(key=source['key'],path=path,sha256=hashed.sha.hexdigest(),size=hashed.size,
                etag=source['etag'],md5=hashed.md5.hexdigest(),identity=identities[path]))
            details.append(dict(key=source['key'],shapes=dict(shapes),anomalies=dict(anomalies)))
            elapsed=perf_counter()-started
            if elapsed-last_progress>=2 or len(result)==len(keys):
                _write(work/'progress.json',dict(receipts=len(result),of=len(keys),source_rows=parsed,
                    rows=sum(r['expected_captures'] for r in result),secs=elapsed));last_progress=elapsed
        recheck_source_pins(pins)
        for path,identity in identities.items():
            if custody_identity(path)!=identity:raise ValueError('Receipt changed before count acceptance')
    except (ValueError,OSError,EOFError,ijson.JSONError) as error:
        _write(work/'error.json',dict(error_class=type(error).__name__,kind='invalid_source',detail=None))
        message=str(error) if type(error) is ValueError else 'Malformed or invalid receipt source: '+type(error).__name__
        raise ValueError(message) from None
    _write(work/'metrics.json',dict(seconds=perf_counter()-started,parser='ijson.basic_parse',
        ijson_version=ijson.__version__,ijson_backend=ijson.backend,parsed_lines=parsed,
        sources=proofs,qualifications=pins,receipts=len(result),details=details,
        expected_captures=sum(r['expected_captures'] for r in result)))
    _write(work/'counts.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('files','receipt-inventory','work'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--source-qualifications',type=Path)
    args=parser.parse_args(argv);inventory=json.loads(args.receipt_inventory.read_text())
    rows=count_sources(files=json.loads(args.files.read_text()),
        receipt_keys=[r if isinstance(r,str) else r['key'] for r in inventory],work=args.work,
        source_qualifications=json.loads(args.source_qualifications.read_text()) if args.source_qualifications else {})
    print(json.dumps(dict(receipts=len(rows),expected_captures=sum(r['expected_captures'] for r in rows))))
    return 0


if __name__=='__main__':raise SystemExit(main())

"""Count protected absolute key names without emitting receipt values."""
from pathlib import Path
import gzip
import json
import re
import time

root = Path('/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts')
start = time.monotonic()
candidate = re.compile(rb'"/(?:[^"\\]|\\.)*"\s*:')
counts = {'lines_with_absolute_keys': 0, 'absolute_key_names': 0,
          'pointer_segments_matching_absolute_keys': 0, 'files': 0}
for file in sorted(root.rglob('*.jsonl.gz')):
    counts['files'] += 1
    with gzip.open(file, 'rb') as stream:
        for raw in stream:
            if not candidate.search(raw):
                continue
            obj = json.loads(raw)
            stack, keys, pointers = [obj], set(), []
            while stack:
                item = stack.pop()
                if isinstance(item,dict):
                    for key,value in item.items():
                        if key.startswith('/'):
                            keys.add(key)
                            counts['absolute_key_names'] += 1
                        if key == 'pointer' and isinstance(value,list):
                            pointers.append(value)
                        if isinstance(value,(dict,list)):
                            stack.append(value)
                elif isinstance(item,list):
                    stack.extend(v for v in item if isinstance(v,(dict,list)))
            if keys:
                counts['lines_with_absolute_keys'] += 1
                counts['pointer_segments_matching_absolute_keys'] += sum(
                    1 for p in pointers for v in p if isinstance(v,str) and v in keys)
result = {'basis':'measured', 'counts':counts,'seconds':round(time.monotonic()-start,3),
          'limits':'Unix-style absolute keys in the local mirror only. Matching pointer segments are counted without proving full path resolution. No live writers, backup, Windows keys, or bucket state tested.'}
Path('receipt-pointer-check.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))

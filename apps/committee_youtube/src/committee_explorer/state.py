"""Bounded, checked Git-safe storage for the persistent ID and issue state."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from .export import encode, file_sha

CHUNK_BYTES=50*1024*1024


def pack(source, output):
    source,output=Path(source),Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.state-',dir=output.parent))
    try:
        archive=stage/'state.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for item in sorted(source.iterdir()):
                if item.name in ('ids.json','publication.json','issue-history','reuse.json'):tar.add(item,arcname=item.name)
        parts=[]
        with archive.open('rb') as stream:
            while raw:=stream.read(CHUNK_BYTES):
                path=f'{len(parts):04d}.part';(stage/path).write_bytes(raw)
                parts.append({'path':path,'sha256':hashlib.sha256(raw).hexdigest(),'byte_size':len(raw)})
        manifest={'schema_version':'1.0','sha256':file_sha(archive),'parts':parts}
        archive.unlink();(stage/'manifest.json').write_bytes(encode(manifest))
        output.mkdir(exist_ok=True)
        for item in stage.iterdir():shutil.copy2(item,output/item.name)
        for old in output.iterdir():
            if old.name not in {p['path'] for p in parts}|{'manifest.json'} and old.is_file():old.unlink()
        return manifest
    finally:shutil.rmtree(stage)


def unpack(source, output):
    source,output=Path(source),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if not (source/'manifest.json').exists():
        if source.exists() and any(source.iterdir()):
            raise ValueError('State checkpoint is nonempty but its manifest is missing')
        return False
    if any(output.iterdir()):raise ValueError('State restore target must be empty')
    manifest=json.loads((source/'manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='explorer-state-') as temporary:
        archive=Path(temporary)/'state.tar.gz'
        with archive.open('wb') as stream:
            for part in manifest['parts']:
                if Path(part['path']).name!=part['path']:raise ValueError('Unsafe state chunk path')
                path=source/part['path']
                if file_sha(path)!=part['sha256'] or path.stat().st_size!=part['byte_size']:raise ValueError('State chunk differs')
                with path.open('rb') as chunk:shutil.copyfileobj(chunk,stream)
        if file_sha(archive)!=manifest['sha256']:raise ValueError('State archive digest differs')
        with tarfile.open(archive,'r:gz') as tar:tar.extractall(output,filter='data')
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['pack','unpack'])
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=(pack if args.action=='pack' else unpack)(args.input,args.output)
    print('State '+args.action+' completed'+(' (no prior state)' if result is False else ''))

if __name__=='__main__':main()

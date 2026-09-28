"""Verify and stage browser data; Parquet files are served unchanged."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from .export import encode, file_sha, sha
from committee_meeting.publication import PublicationManifest

MEDIA_TYPE = 'application/vnd.committee-explorer+json+gzip'


def verify(directory):
    root = Path(directory)
    pointer = json.loads((root / 'CURRENT.json').read_text())
    manifest_path = root / pointer['manifest_path']
    if file_sha(manifest_path) != pointer['manifest_sha256']: raise ValueError('Manifest digest mismatch')
    manifest = PublicationManifest.model_validate_json(manifest_path.read_bytes())
    if manifest.publication_id != pointer['publication_id']: raise ValueError('Publication identity mismatch')
    for part in manifest.partitions:
        path = manifest_path.parent / part.path
        if not path.is_relative_to(manifest_path.parent) or '..' in Path(part.path).parts: raise ValueError('Unsafe partition path')
        if file_sha(path) != part.sha256 or path.stat().st_size != part.byte_size: raise ValueError('Partition differs: '+part.path)
    return pointer, manifest_path.parent, manifest


def package(input_dir, output_dir, *, max_bytes=900_000_000):
    _, source, manifest = verify(input_dir)
    output = Path(output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.browser-', dir=output.parent))
    try:
        # Catalog and the big compatibility index are downloadable/offline views,
        # not prerequisites for the browser query/record reader.
        parts = [p for p in manifest.partitions if p.role != 'download' and p.schema_name not in ('committee_explorer.meetings', 'congress_api.print-decisions')]
        # Opaque suffix keeps static servers from adding Content-Encoding:gzip:
        # fetch must receive the stored bytes so manifest digests remain valid.
        parquet = any(p.media_type == 'application/vnd.apache.parquet' for p in parts)
        replacements = {p.path: p.path if parquet else p.path + '.data' for p in parts}
        def remap(value):
            if isinstance(value, dict): return {k: remap(v) for k,v in value.items()}
            if isinstance(value, list): return [remap(v) for v in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        compressed = []
        for part in parts:
            raw = (source / part.path).read_bytes()
            if not parquet and part.schema_name in ('committee_explorer.locations','committee_explorer.location-bucket','committee_explorer.queries','committee_explorer.relations','committee_explorer.relation-bucket'):
                raw = encode(remap(json.loads(raw)))
            if not parquet: raw = gzip.compress(raw, compresslevel=6, mtime=0)
            path = replacements[part.path]
            target = stage / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            compressed.append(part.model_copy(update={'path':path,'media_type':part.media_type if parquet else MEDIA_TYPE,'sha256':sha(raw),'byte_size':len(raw)}))
        publication_id = sha(encode({'source_publication':manifest.publication_id,'files':[p.sha256 for p in compressed]}))[:24]
        packaged = manifest.model_copy(update={'publication_id':publication_id, 'partitions':tuple(compressed),
            'limitations':(*manifest.limitations, 'Browser distribution: original publication '+manifest.publication_id+'. Complete Catalog and legacy meeting index are excluded; query pages retain browse coverage.')})
        # Exercise schema validators after edits, before publishing.
        packaged = PublicationManifest.model_validate(packaged)
        manifest_raw = encode(packaged.model_dump(mode='json'));(stage/'manifest.json').write_bytes(manifest_raw)
        total = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        if total > max_bytes: raise ValueError(f'Browser publication {total} bytes exceeds {max_bytes} byte budget')
        release = output/'releases'/publication_id;release.parent.mkdir(parents=True,exist_ok=True)
        if release.exists(): shutil.rmtree(stage)
        else: stage.rename(release)
        pointer = {'schema_version':manifest.schema_version,'publication_id':publication_id,'manifest_path':f'releases/{publication_id}/manifest.json','manifest_sha256':sha(manifest_raw),'media_type':'application/json'}
        temporary=output/'.CURRENT.json.tmp';temporary.write_bytes(encode(pointer));temporary.replace(output/'CURRENT.json')
        verify(output)
        # A static deployment carries exactly its current release. Old full/local
        # publications remain outside this browser distribution.
        for old in (output/'releases').iterdir():
            if old.name != publication_id and old.is_dir(): shutil.rmtree(old)
        return packaged, total
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--verify',type=Path);p.add_argument('--max-bytes',type=int,default=900_000_000)
    a=p.parse_args()
    if a.verify:
        _,_,m=verify(a.verify);print(f'Verified {m.publication_id}: {len(m.partitions)} files');return
    if a.input is None or a.output is None:p.error('--input and --output are required')
    m,total=package(a.input,a.output,max_bytes=a.max_bytes);print(f'Browser publication {m.publication_id}: {total} bytes, {len(m.partitions)} files')

if __name__=='__main__':main()

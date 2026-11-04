"""Fetch the spicy-regs tables a model spec pins, from the source its manifest names.

A hosted publisher has the checked-in manifest but none of the Parquet files beside it.
Each table is read from ``<source>/<path>`` and kept only when its sha256 and size equal
the manifest's pin; a file already holding the pinned bytes is not fetched again.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
from urllib.request import Request,urlopen

from viewer_publication.constants import USER_AGENT

CHUNK=1<<20


def _open(url):
    # The r2.dev origin refuses urllib's default User-Agent with 403.
    return urlopen(Request(url,headers={'User-Agent':USER_AGENT}),timeout=120)


def _digest(path):
    h=hashlib.sha256();size=0
    with open(path,'rb') as source:
        for block in iter(lambda:source.read(CHUNK),b''):h.update(block);size+=len(block)
    return h.hexdigest(),size


def _download(url,partial,limit,opener):
    """Write at most limit+1 bytes, so an oversized response fails the size check."""
    written=0
    with opener(url) as response,open(partial,'wb') as out:
        while written<=limit:
            block=response.read(min(CHUNK,limit+1-written))
            if not block:break
            out.write(block);written+=len(block)


def fetch_pinned(pin,*,opener=_open):
    """Hold every table of the pinned manifest beside it; refuse any byte that differs."""
    manifest=Path(pin['path'])
    if _digest(manifest)!=(pin['sha256'],pin['size']):
        raise ValueError('spicy-regs manifest does not match its pin: '+str(manifest))
    value=json.loads(manifest.read_text(encoding='utf-8'))
    source=value['source'].rstrip('/')
    if not source.startswith('https://'):raise ValueError('spicy-regs source must be an https origin')
    report={}
    for name,table in sorted(value['tables'].items()):
        relative=PurePosixPath(table['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('spicy-regs table path must stay under its manifest: '+name)
        target=manifest.parent.joinpath(*relative.parts)
        expected=(table['sha256'],table['size'])
        if target.is_file() and _digest(target)==expected:
            report[name]='present';continue
        target.parent.mkdir(parents=True,exist_ok=True)
        partial=target.with_name(target.name+'.partial')
        try:
            _download(source+'/'+relative.as_posix(),partial,table['size'],opener)
            if _digest(partial)!=expected:raise ValueError('spicy-regs table does not match its pin: '+name)
            os.replace(partial,target)
        finally:
            partial.unlink(missing_ok=True)
        report[name]='fetched'
    return dict(status='ready',source=source,tables=report)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-spec',type=Path,required=True)
    args=parser.parse_args(argv)
    from viewer_publication.archive_model_job import load_spec
    try:
        pin=load_spec(args.model_spec).get('spicy_regs')
        result=dict(status='none',tables={}) if pin is None else fetch_pinned(pin)
    except (ValueError,OSError,KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

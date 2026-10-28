"""Typed public receipts: source bodies first, then one create-only receipt."""
from datetime import date
from dataclasses import replace
import gzip
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from congress_api.models.raw_fetch import FetchResult
from congress_api.parsers.source_family import family as source_family
from congress_api.retention.archive_expander import expand_archive
from congress_api.retention.body_store import validate_record
from congress_api.retention.receipt_privacy import public_receipt
from congress_api.retention.sniff import read_sniff_file, SniffResourceError

HEADERS = frozenset('content-type content-length content-disposition last-modified etag content-encoding retry-after date cache-control accept-ranges'.split())
TOKEN = re.compile(r'[A-Za-z0-9_.-]+')
ERROR_CODE = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,79}')


def _part(value):
    return isinstance(value,str) and TOKEN.fullmatch(value) and value not in {'.','..'}


def _identity(identity):
    if (set(identity) != {'job','commit','lockfile_digest'}
            or not isinstance(identity['job'],str) or not identity['job']
            or re.fullmatch(r'[0-9a-f]{40}',identity['commit']) is None
            or re.fullmatch(r'[0-9a-f]{64}',identity['lockfile_digest']) is None):
        raise ValueError('Invalid receipt writer identity')
    return dict(identity)


def outcome(attempt, stored):
    """Use transfer/status facts, with body-store results only for good fetches."""
    if 'retry-after' in attempt.headers or attempt.http_status in {429,503}:
        return 'retry_later'
    if not attempt.complete or attempt.error:
        return 'size_limit' if attempt.error in {'size_limit','response_limit','source_response_limit'} else 'request_failed'
    if attempt.http_status is not None and 200 <= attempt.http_status < 300:
        if stored is None:
            raise ValueError('Complete successful attempt has no body')
        return stored.outcome
    return 'failed'


def _inspect_stored(body):
    """Enrich uninspected transfer facts only after body storage has succeeded."""
    if body.path is None or any(value is not None for value in (
            body.sniffed_format,body.sniff_version,body.intact,body.sniff_error)):
        return body
    try:
        reading=read_sniff_file(body.path)
    except (OSError,SniffResourceError) as error:
        code=getattr(error,'error_type',None)
        return replace(body,sniff_error=code if isinstance(code,str) and ERROR_CODE.fullmatch(code)
                       else type(error).__name__)
    return replace(body,sniffed_format=reading['format'],sniff_version=reading['parser_version'],
                   intact=reading['intact'],sniff_error=reading['error_type'])


class ReceiptWriter:
    def __init__(self, store, *, identity, run_id, write_date, archive_limits):
        self.identity = _identity(identity)
        if not _part(run_id) or date.fromisoformat(write_date).isoformat() != write_date:
            raise ValueError('Receipt needs a fresh run ID and UTC write date')
        self.store, self.run_id, self.write_date = store,run_id,write_date
        self.archive_limits, self.sequence = archive_limits,0

    def write(self, result: FetchResult, *, family=None, observations=(), mode='fetch', recovery_evidence=None, fidelity=None):
        final = result.final
        family = family or source_family(url=final.requested_url)
        if not family or not all(_part(part) for part in family.split('/')):
            raise ValueError('Invalid receipt source family')
        if mode not in {'fetch','retained_import'} or mode == 'retained_import' and recovery_evidence is None:
            raise ValueError('Recovery import requires recovery evidence')
        fidelity = fidelity or ('retained-file' if mode == 'retained_import' else 'exact-bytes')
        if fidelity not in {'exact-bytes','saved-text','saved-record','retained-file'}:
            raise ValueError('Invalid capture fidelity')
        attempts = (final,*result.prior_attempts)
        if any(a.body is not None and a.body.path is None and
               (mode != 'retained_import' or a.body.stored_suffix not in {'','.gz'}) for a in attempts):
            raise ValueError('Only retained imports can reference an existing raw body')
        codes = [a.error for a in attempts]+[a.body.sniff_error for a in attempts if a.body]
        if any(code is not None and (not isinstance(code,str) or not ERROR_CODE.fullmatch(code)) for code in codes):
            raise ValueError('Invalid stable raw error code')
        line = dict(run_id=self.run_id,mode=mode,family=family,requested_url=final.requested_url,
            url=final.url,retrieved_at=final.retrieved_at,http_status=final.http_status,
            provider_status=final.provider_status,outcome=None,transport=final.transport,
            response_headers={k:v for k,v in final.headers.items() if k in HEADERS},
            redirects=list(final.redirects),prior_attempts=[dict(url=a.url,retrieved_at=a.retrieved_at,
                transport=a.transport,http_status=a.http_status,sha256=a.body.sha256 if a.body else None)
                for a in result.prior_attempts],source_context=dict(observations=list(observations)),
            writer=self.identity,captures=[])
        if final.error is not None:
            line['error_type'] = final.error
        if recovery_evidence is not None:
            line.update(publisher_requested=False,recovery_evidence=recovery_evidence)
        # Refuse every attempt URL, including redirects and observations, before
        # reading/expanding bodies or calling the raw adapter.
        validate_record([line,*[dict(requested_url=a.requested_url,url=a.url,redirects=list(a.redirects)) for a in attempts]])
        line = public_receipt(line)
        final_write = None
        with TemporaryDirectory(prefix='raw-receipt-') as temporary:
            temporary = Path(temporary)
            for attempt_index, attempt in enumerate(attempts):
                if attempt.body is None:
                    continue
                body = attempt.body
                key = f'bodies/sha256/{body.sha256[:2]}/{body.sha256}'
                stored = (self.store.reference(key,stored_suffix=body.stored_suffix) if body.path is None else
                          self.store.put(key,body.path,body.media_type or 'application/octet-stream'))
                body = _inspect_stored(body)
                if attempt_index == 0:
                    final_write = stored
                capture = self._capture(body,attempt,attempt_index,stored,None,None,fidelity)
                line['captures'].append(capture)
                if (body.path is not None and body.sniff_error is None and attempt.complete
                        and self.archive_limits is not None):
                    expansion = expand_archive(body.path,directory=temporary/str(attempt_index),limits=self.archive_limits)
                    capture['expansion'] = expansion.status
                    for member in expansion.members:
                        member_key = f'bodies/sha256/{member.body.sha256[:2]}/{member.body.sha256}'
                        retained = self.store.put(member_key,member.body.path,
                                                  member.body.media_type or 'application/octet-stream')
                        line['captures'].append(self._capture(member.body,attempt,attempt_index,retained,
                                                              member.member_path,member.entry_index,fidelity))
            line['outcome'] = outcome(final,final_write)
            self.sequence += 1
            key = f'receipts/{family}/{self.write_date}/{self.run_id}-{self.sequence:06d}.jsonl.gz'
            path = temporary/'receipt.jsonl.gz'
            payload = (json.dumps(line,ensure_ascii=False,separators=(',',':'))+'\n').encode()
            path.write_bytes(gzip.compress(payload,mtime=0))
            self.store.put(key,path,'application/x-ndjson')
        return key,line

    @staticmethod
    def _capture(body,attempt,index,stored,member_path,entry_index,fidelity):
        pointer = ['content','body'] if index == 0 else ['prior_attempts',index-1,'content','body']
        if member_path is not None:
            pointer = [*pointer[:-2],'archive_members',entry_index,'content','body']
        capture = dict(pointer=pointer,attempt=index,complete=attempt.complete,
            context_url=attempt.url,member_path=member_path,entry_index=entry_index,expansion=None,
            sha256=body.sha256,bytes=body.size,media_type=body.media_type,sniffed_format=body.sniffed_format,
            sniff_version=body.sniff_version,intact=body.intact,stored_suffix=stored.suffix,fidelity=fidelity)
        if body.sniff_error is not None:
            capture['sniff_error'] = body.sniff_error
        if stored.outcome == 'stored':
            capture.update(stored_md5=stored.md5,stored_bytes=stored.size)
        return capture

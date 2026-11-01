"""Durable raw acquisition, with explicit uncertain remote outcomes.

Only immutable transfer metadata and owned files are retained. A started call
without sealed metadata is uncertain and cannot silently be sent again.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult, Transfer
from congress_api.retention.provenance import durable_json


class UnknownRemoteOutcome(RuntimeError):
    pass


def encode_result(result):
    def attempt(value):
        row=asdict(value)
        if value.body is not None:row['body']['path']=str(value.body.path) if value.body.path else None
        return row
    return dict(final=attempt(result.final),prior_attempts=[attempt(a) for a in result.prior_attempts])


def decode_result(value):
    def attempt(row):
        row=dict(row)
        if row['body'] is not None:
            body=dict(row['body']);body['path']=Path(body['path']) if body['path'] else None
            row['body']=BodyFile(**body)
        row['redirects']=tuple(row['redirects'])
        return FetchAttempt(**row)
    return FetchResult(attempt(value['final']),tuple(attempt(a) for a in value['prior_attempts']))


def _checked_file(path, sha, size):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=size:
        raise ValueError('Sealed acquisition body changed')
    with path.open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest()!=sha:
            raise ValueError('Sealed acquisition body digest changed')


class DurableCapture:
    def __init__(self,root,binding):
        self.root=Path(root)
        if self.root.is_symlink():raise ValueError('Acquisition journal must not be a symlink')
        self.root.mkdir(parents=True,exist_ok=True)
        selected=self.root/'binding.json'
        if selected.exists():
            if json.loads(selected.read_text())!=binding:raise ValueError('Capture continuation inputs changed')
        else:durable_json(selected,binding)

    def directory(self,operation_id):
        if not isinstance(operation_id,str) or re.fullmatch('[a-zA-Z0-9_.-]+',operation_id) is None or operation_id in {'.','..'}:
            raise ValueError('Invalid acquisition operation ID')
        root=self.root/operation_id
        if root.is_symlink():raise ValueError('Acquisition operation must not be a symlink')
        root.mkdir(exist_ok=True)
        return root

    def fetch(self,operation_id,url,fetcher_factory):
        root=self.directory(operation_id);metadata=root/'downloaded.json'
        if metadata.exists():
            result=decode_result(json.loads(metadata.read_text()))
            if result.final.requested_url!=url:raise ValueError('Acquisition operation URL changed')
            for attempt in (result.final,*result.prior_attempts):
                if attempt.body and attempt.body.path:
                    if not attempt.body.path.resolve().is_relative_to(root.resolve()):raise ValueError('Acquisition body escapes its owner')
                    _checked_file(attempt.body.path,attempt.body.sha256,attempt.body.size)
            return result
        fetcher=fetcher_factory(root)
        fetcher.direct=self.adapter(operation_id,fetcher.direct,'direct')
        if fetcher.provider is not None:fetcher.provider=self.adapter(operation_id,fetcher.provider,'zyte')
        if getattr(fetcher,'firecrawl',None) is not None:fetcher.firecrawl=self.adapter(operation_id,fetcher.firecrawl,'firecrawl')
        result=fetcher.fetch(url)
        for attempt in (result.final,*result.prior_attempts):
            if attempt.body and attempt.body.path:
                with attempt.body.path.open('rb') as source:os.fsync(source.fileno())
        durable_json(metadata,encode_result(result))
        return result

    def adapter(self,operation_id,adapter,kind):
        root=self.directory(operation_id)
        owner=self
        class JournalAdapter:
            sequence=0
            def hop(self,url,destination,*,limit,headers):
                index=self.sequence;self.sequence+=1
                record=root/f'{kind}-{index}.json'
                owned=root/f'{kind}-{index}.sealed'
                # Header values can contain credentials; bind by hash only.
                request=dict(url=url,limit=limit,headers_sha256=hashlib.sha256(json.dumps(headers,sort_keys=True).encode()).hexdigest())
                previous=json.loads(record.read_text()) if record.exists() else None
                decision=root/f'{kind}-{index}.unknown.json'
                if previous is not None and decision.exists() and json.loads(decision.read_text())['previous']==previous:
                    owner._finish_retry(root,kind,index)
                    previous=None
                if previous is not None:
                    if previous['request']!=request:raise ValueError('Durable request definition changed')
                    if previous['phase']=='started':raise UnknownRemoteOutcome('Remote outcome is unknown; reconcile or record an explicit retry decision')
                    facts=dict(previous['transfer']);_checked_file(owned,facts['sha256'],facts['size'])
                else:
                    started=dict(phase='started',request=request,attempt_token=uuid4().hex)
                    durable_json(record,started)
                    from congress_api.acquisition.admission import AdmissionDenied
                    try:transfer=adapter.hop(url,owned,limit=limit,headers=headers)
                    except AdmissionDenied:
                        record.unlink()  # No network call was admitted.
                        raise
                    except Exception as error:
                        partial=None
                        if owned.exists():
                            with owned.open('rb') as source:
                                partial=dict(sha256=hashlib.file_digest(source,'sha256').hexdigest(),size=owned.stat().st_size)
                                os.fsync(source.fileno())
                        durable_json(record,dict(started,error_type=type(error).__name__,partial=partial,
                            reservation_id=getattr(adapter,'last_attempt',None),wire_reservation_id=getattr(adapter,'last_wire_attempt',None)))
                        raise UnknownRemoteOutcome('Network outcome is unknown; evidence and reservation remain protected') from None
                    # Adapters may return errors without a file. Retain an empty
                    # evidence file so the completed response still resumes.
                    if not owned.exists():owned.touch()
                    # Redirect bodies are unused by Fetcher and receipt semantics;
                    # retain their response facts, not potentially seven full files.
                    redirected=transfer.http_status in {301,302,303,307,308} and transfer.headers.get('location')
                    if redirected:
                        with owned.open('wb') as target:target.flush();os.fsync(target.fileno())
                    with owned.open('rb') as source:
                        sha=(hashlib.sha256(b'').hexdigest() if redirected else transfer.sha256 or hashlib.file_digest(source,'sha256').hexdigest())
                        os.fsync(source.fileno())
                    facts=asdict(transfer);facts.update(path=str(owned),sha256=sha,size=owned.stat().st_size)
                    durable_json(record,dict(phase='downloaded',request=request,transfer=facts))
                # Fetcher removes redirect files; a hard link keeps sealed custody.
                os.link(owned,destination)
                facts['path']=Path(destination)
                return Transfer(**facts)
        return JournalAdapter()

    def cleanup(self,operation_id):
        root=self.directory(operation_id)
        if not (root/'committed.json').exists():raise ValueError('Unacknowledged acquisition is protected')
        # Delete owned payloads only, never a caller directory or frozen receipt.
        for pattern in ('*.sealed','*.body'):
            for path in root.glob(pattern):
                if path.is_symlink():raise ValueError('Unexpected capture scratch symlink')
                path.unlink()

    def retry_unknown(self,operation_id,kind,index,*,reason):
        """Authorize one recorded retry; the uncertain call stays charged forever.

        Call this between capture runs, while their work lock is released.
        The caller must supply its reviewed retry decision, not silently retry
        started operations during ordinary continuation.
        """
        if kind not in {'direct','zyte','firecrawl'} or type(index) is not int or index<0 or not isinstance(reason,str) or not reason.strip():
            raise ValueError('Invalid unknown-outcome retry decision')
        root=self.directory(operation_id);path=root/f'{kind}-{index}.json'
        previous=json.loads(path.read_text())
        decision=root/f'{kind}-{index}.unknown.json'
        if previous['phase']!='started' or decision.exists():raise ValueError('Only one bounded retry of an unknown call is allowed')
        durable_json(decision,dict(previous=previous,reason=reason))
        self._finish_retry(root,kind,index)

    @staticmethod
    def _finish_retry(root,kind,index):
        path=root/f'{kind}-{index}.json';owned=root/f'{kind}-{index}.sealed'
        quarantine=root/'quarantine';quarantine.mkdir(exist_ok=True)
        retained=quarantine/f'{kind}-{index}.body'
        if owned.exists():os.replace(owned,retained)
        if path.exists():path.unlink()
        for directory in (quarantine,root):
            descriptor=os.open(directory,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)

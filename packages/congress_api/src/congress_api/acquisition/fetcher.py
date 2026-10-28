"""Raw fetch policy: explicit scope, one-hop adapters and owned spool files."""
from datetime import datetime, timezone
import hashlib
import ipaddress
import re
from pathlib import Path
from uuid import uuid4
from urllib.parse import urljoin, urlsplit

import requests

from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
from congress_api.retention.body_store import validate_record


class CaptureScope:
    """A supplied allowlist plus exclusions; every resolved address must be public."""
    def __init__(self, patterns, exclusions, *, resolve):
        if not patterns:
            raise ValueError('Capture scope needs an explicit allowlist')
        self.patterns = tuple(map(re.compile, patterns))
        self.exclusions = tuple(map(re.compile, exclusions))
        self.resolve = resolve

    def __call__(self, url):
        try:
            validate_record(url)
            parts = urlsplit(url)
            host = parts.hostname
            if (parts.scheme not in {'http','https'} or not host or parts.username is not None
                    or parts.password is not None or host == 'localhost' or host.endswith(('.local','.internal'))
                    or not any(p.fullmatch(url) for p in self.patterns)
                    or any(p.search(url) for p in self.exclusions)):
                return False
            try:
                addresses = [str(ipaddress.ip_address(host))]
            except ValueError:
                addresses = self.resolve(host)
            return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)
        except (ValueError, OSError):
            return False


class Fetcher:
    def __init__(self, *, scope, direct, provider, pace, directory, spool_limit, headers=None, clock=None):
        if not spool_limit > 0:
            raise ValueError('Spool limit must be positive')
        self.scope, self.direct, self.provider, self.pace = scope, direct, provider, pace
        self.directory, self.spool_limit = Path(directory), spool_limit
        self.headers = headers or (lambda url: {})
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def fetch(self, url):
        if not self.scope(url):
            raise ValueError('URL is outside capture scope')
        first = self._attempt(url, self.direct, 'direct', self.spool_limit)
        # A received HTTP failure is evidence; provider fallback is for failed
        # transfers and access refusal, never for document/page classification.
        retry_after = 'retry-after' in first.headers or first.http_status in {429,503}
        if (self.provider is None or retry_after or first.error in {'excluded_redirect','redirect_limit'}
                or first.complete and first.http_status not in {401,403}):
            return FetchResult(first)
        remaining = self.spool_limit-(first.body.size if first.body else 0)
        if remaining <= 0:
            return FetchResult(first)
        return FetchResult(self._attempt(url, self.provider, 'zyte',remaining), (first,))

    def _attempt(self, requested, adapter, transport, limit):
        target, redirects, timestamp = requested, [], self.clock()
        self.directory.mkdir(parents=True,exist_ok=True)
        for step in range(7):
            if not self.scope(target):
                return FetchAttempt(requested,target,timestamp,transport,None,None,{},tuple(redirects),False,None,'excluded_redirect')
            self.pace(target,transport)
            destination = self.directory/(uuid4().hex+'.body')
            try:
                transfer = adapter.hop(target,destination,limit=min(limit,5*1024**3),headers=self.headers(target))
            except (requests.RequestException, OSError) as exc:
                destination.unlink(missing_ok=True)
                return FetchAttempt(requested,target,timestamp,transport,None,None,{},tuple(redirects),False,None,type(exc).__name__)
            headers = {k.lower(): v for k,v in transfer.headers.items()}
            observe = getattr(self.pace,'observe',None)
            if observe is not None:
                observe(target,transport,transfer.http_status,headers)
            valid_final = self.scope(transfer.url)
            if transfer.http_status in {301,302,303,307,308} and headers.get('location') and valid_final:
                redirects.append(dict(url=transfer.url,http_status=transfer.http_status))
                destination.unlink(missing_ok=True)
                if step == 6:
                    return FetchAttempt(requested,transfer.url,timestamp,transport,transfer.http_status,
                        transfer.provider_status,headers,tuple(redirects),False,None,'redirect_limit')
                target = urljoin(transfer.url,headers['location'])
                continue
            body = None
            if destination.exists():
                size = transfer.size if transfer.size is not None else destination.stat().st_size
                sha = transfer.sha256
                if sha is None:
                    with destination.open('rb') as source:
                        sha = hashlib.file_digest(source,'sha256').hexdigest()
                body = BodyFile(destination,sha,size,headers.get('content-type'),None,None,None)
            return FetchAttempt(requested,transfer.url,timestamp,transport,transfer.http_status,
                transfer.provider_status,headers,tuple(redirects),transfer.complete and valid_final,body,
                transfer.error if valid_final else 'excluded_redirect')


class HostPacer:
    """Per-host starts and server waits from an explicit raw-writer registry."""
    def __init__(self, registry, *, clock=None, sleep=None, utc_now=None):
        import math
        import threading
        import time
        self.default_gap = registry['default_gap_seconds']
        self.provider_gap = registry['provider_gap_seconds']
        self.hosts = registry['hosts']
        values = [self.default_gap,self.provider_gap]
        for policy in self.hosts.values():
            values.extend([policy['gap_seconds'],*policy.get('backoffs',{}).values()])
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError('Host pacing values must be finite and nonnegative')
        self.clock,self.sleep,self.utc_now = clock or time.monotonic,sleep or time.sleep,utc_now or time.time
        self.lock,self.deadlines,self.starts = threading.Lock(),{},{}
        self.new_lock = threading.Lock

    def __call__(self,url,transport):
        host = urlsplit(url).hostname
        key = (host,transport)
        gap = self.provider_gap if transport == 'zyte' else self.hosts.get(host,{}).get('gap_seconds',self.default_gap)
        with self.lock:
            gate = self.starts.setdefault(key,self.new_lock())
        # Serialize starts for this host only. Observations use the short
        # deadline lock and may extend a wait while this caller is asleep.
        with gate:
            while True:
                with self.lock:
                    delay = max(0,self.deadlines.get(key,0)-self.clock())
                    if not delay:
                        self.deadlines[key] = self.clock()+gap
                        return
                self.sleep(delay)

    def observe(self,url,transport,status,headers):
        from email.utils import parsedate_to_datetime
        host = urlsplit(url).hostname
        delay = self.hosts.get(host,{}).get('backoffs',{}).get(str(status),0)
        value = headers.get('retry-after')
        if value:
            try:
                seconds = int(value) if str(value).isdigit() else parsedate_to_datetime(value).timestamp()-self.utc_now()
                delay = max(delay,seconds)
            except (ValueError,TypeError,OverflowError):
                pass  # Preserve invalid server text in the receipt, never invent a date.
        with self.lock:
            key = (host,transport)
            self.deadlines[key] = max(self.deadlines.get(key,0),self.clock()+delay)

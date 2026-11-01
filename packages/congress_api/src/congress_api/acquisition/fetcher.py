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

    def matches_static(self, url):
        """Check URL syntax, allowlist and exclusions without resolving the host."""
        try:
            validate_record(url)
            parts = urlsplit(url)
            host = parts.hostname
        except ValueError:
            return False
        return not (parts.scheme not in {'http','https'} or not host or parts.username is not None
                    or parts.password is not None or host == 'localhost' or host.endswith(('.local','.internal'))
                    or not any(p.fullmatch(url) for p in self.patterns)
                    or any(p.search(url) for p in self.exclusions))

    def __call__(self, url):
        if not self.matches_static(url):
            return False
        try:
            host = urlsplit(url).hostname
            try:
                addresses = [str(ipaddress.ip_address(host))]
            except ValueError:
                addresses = self.resolve(host)
            return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)
        except (ValueError, OSError):
            return False


class Fetcher:
    def __init__(self, *, scope, direct, provider, pace, directory, spool_limit, headers=None, clock=None, firecrawl=None):
        if not spool_limit > 0:
            raise ValueError('Spool limit must be positive')
        self.scope, self.direct, self.provider, self.pace = scope, direct, provider, pace
        self.firecrawl=firecrawl
        self.directory, self.spool_limit = Path(directory), spool_limit
        self.headers = headers or (lambda url: {})
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def fetch(self, url):
        if not self.scope(url):
            raise ValueError('URL is outside capture scope')
        attempts=[];remaining=self.spool_limit
        for adapter,transport in ((self.direct,'direct'),(self.provider,'zyte'),(self.firecrawl,'firecrawl')):
            if adapter is None:continue
            current=self._attempt(url,adapter,transport,remaining)
            attempts.append(current)
            remaining-=current.body.size if current.body else 0
            if (remaining<=0 or not self._escalate(current)):
                break
        return FetchResult(attempts[-1],tuple(attempts[:-1]))

    @staticmethod
    def _escalate(attempt):
        # An origin throttle applies to every provider; a provider quota applies
        # only to that provider and does not invent an origin HTTP status.
        if attempt.transport!='direct' and (attempt.provider_status in {401,402,403,429}
                or attempt.error in {'provider_quota','provider_credits','provider_http_error','invalid_provider_response'}):
            return False
        if ('retry-after' in attempt.headers or attempt.http_status in {429,503,404,410}
                or attempt.error in {'excluded_redirect','redirect_limit','size_limit'}):
            return False
        if not attempt.complete or attempt.error or attempt.http_status in {401,403}:return True
        if attempt.http_status is None or not 200<=attempt.http_status<300 or attempt.body is None:return False
        with attempt.body.path.open('rb') as source:prefix=source.read(65536)
        lowered=prefix.lower().lstrip()
        html=lowered.startswith((b'<!doctype html',b'<html')) or b'<html' in lowered[:1024]
        expected_pdf=urlsplit(attempt.requested_url).path.lower().endswith('.pdf') or 'application/pdf' in (attempt.headers.get('content-type','').lower())
        wall=html and any(marker in lowered for marker in (b'captcha',b'access denied',b'just a moment',b'cf-chl-',b'cloudflare ray id',b'verify you are human'))
        return bool(wall or expected_pdf and not prefix.startswith(b'%PDF-'))

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
                code = getattr(exc, 'capture_error', None)
                return FetchAttempt(requested,target,timestamp,transport,None,None,{},tuple(redirects),False,None,
                    code if isinstance(code, str) and code else type(exc).__name__)
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
        self.new_lock, self.origin_deadlines = threading.Lock, {}

    def __call__(self,url,transport):
        host = urlsplit(url).hostname
        key = (host,transport)
        gap = self.provider_gap if transport in {'zyte','firecrawl'} else self.hosts.get(host,{}).get('gap_seconds',self.default_gap)
        with self.lock:
            gate = self.starts.setdefault(key,self.new_lock())
        # Serialize starts for this host only. Observations use the short
        # deadline lock and may extend a wait while this caller is asleep.
        with gate:
            while True:
                with self.lock:
                    delay = max(0,max(self.deadlines.get(key,0),self.origin_deadlines.get(host,0))-self.clock())
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
            if status in {429,503} or value:
                self.origin_deadlines[host] = max(self.origin_deadlines.get(host,0),self.clock()+delay)

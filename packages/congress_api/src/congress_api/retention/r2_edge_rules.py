"""Declarative Cloudflare R2 Custom Domain, CORS, WAF, and Transform Rule contract."""

from pathlib import Path
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit


DEFAULT_EDGE_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / 'infra'
    / 'cloudflare'
    / 'congressional-data-r2-edge.json'
)

PUBLIC_HOSTNAME = 'congressional-data.spicygov.ai'
PUBLIC_BUCKET = 'congressional-tech-raw'

_VIEWER_MANIFEST_RE = re.compile(
    r'^/viewer-publications/(?:manifest\.json|catalogs/[a-f0-9]{32}\.json|releases/[a-f0-9]{32}/manifest\.json|releases/[a-f0-9]{32}/[a-f0-9]{32}/viewer-v2/recovery-status\.json)$'
)
_VIEWER_RELEASE_ASSET_RE = re.compile(
    r'^/viewer-publications/releases/[a-f0-9]{32}/(?:[a-f0-9]{32}/viewer-v2/(?:manifest\.json|search\.parquet|sources\.parquet|details\.parquet|recoveries\.parquet|observations(?:\.index\.json|\.blocks\.br|\.refs\.br))|[A-Za-z0-9._-]+-(?:filenames|documents|sources)\.parquet)$'
)
_BODY_OBJECT_RE = re.compile(r'^/bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})\.(pdf|gz)$')
_EXPORTS_OBJECT_RE = re.compile(
    r'^/exports/(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*[A-Za-z0-9][A-Za-z0-9._-]*\.(?:json|parquet|bin|br|gz|csv|zst|ipc|arrow)$'
)


def load_edge_config(path=None):
    """Load the declarative Cloudflare R2 custom-domain edge configuration."""
    target = Path(path) if path is not None else DEFAULT_EDGE_CONFIG_PATH
    return json.loads(target.read_text(encoding='utf-8'))


def sanitize_download_filename(raw_filename):
    """Sanitize a ?filename= query parameter for RFC 6266 Content-Disposition."""
    if not isinstance(raw_filename, str) or not raw_filename:
        return None
    try:
        decoded = unquote(raw_filename)
    except Exception:
        return None
    if not decoded or len(decoded) > 200:
        return None
    if '/' in decoded or '\\' in decoded or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded):
        return None
    return decoded


def format_content_disposition(disposition_type, filename=None):
    """Build an RFC 6266 Content-Disposition header value."""
    safe = sanitize_download_filename(filename)
    if not safe:
        return disposition_type
    ascii_fallback = re.sub(r'[^\x20-\x7e]', '_', safe).replace('\\', '_').replace('"', '_')
    encoded = quote(safe, safe='')
    for ch in ("'", '(', ')', '*'):
        encoded = encoded.replace(ch, f'%{ord(ch):02X}')
    return f'{disposition_type}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def evaluate_waf_request(method, url_or_path, *, config=None):
    """Evaluate the Cloudflare WAF Custom Rule prefix allowlist on congressional-data.spicygov.ai."""
    cfg = config or load_edge_config()
    parsed = urlsplit(url_or_path)
    host = parsed.hostname or cfg['custom_domain']['hostname']
    path = parsed.path or '/'
    upper_method = (method or 'GET').upper()

    if host != cfg['custom_domain']['hostname']:
        return dict(allowed=False, status_code=403, reason='host_mismatch')
    if upper_method not in {'GET', 'HEAD', 'OPTIONS'}:
        return dict(allowed=False, status_code=403, reason='method_not_allowed')
    if '..' in path or '//' in path:
        return dict(allowed=False, status_code=403, reason='path_traversal')

    for blocked in cfg['waf_custom_rules'][0]['blocked_prefixes']:
        if path.startswith(blocked) or path == blocked.rstrip('/'):
            return dict(allowed=False, status_code=403, reason=f'blocked_prefix:{blocked}')

    if path.startswith('/viewer-publications/'):
        if _VIEWER_MANIFEST_RE.match(path) or _VIEWER_RELEASE_ASSET_RE.match(path):
            return dict(allowed=True, status_code=200, prefix='/viewer-publications/')
        return dict(allowed=False, status_code=403, reason='unallowed_viewer_publication_path')

    if path.startswith('/bodies/sha256/'):
        match = _BODY_OBJECT_RE.match(path)
        if match and match.group(1) == match.group(2)[:2]:
            return dict(
                allowed=True,
                status_code=200,
                prefix='/bodies/sha256/',
                sha256=match.group(2),
                extension=match.group(3),
            )
        return dict(allowed=False, status_code=403, reason='invalid_body_object_path')

    if path.startswith('/exports/'):
        if '/accepted-' not in path and _EXPORTS_OBJECT_RE.match(path):
            return dict(allowed=True, status_code=200, prefix='/exports/')
        return dict(allowed=False, status_code=403, reason='unallowed_exports_path')

    return dict(allowed=False, status_code=403, reason='outside_prefix_allowlist')


def evaluate_response_headers(url_or_path, *, content_type=None, config=None):
    """Evaluate Cloudflare HTTP Response Header Transform Rules for a public R2 object response."""
    cfg = config or load_edge_config()
    parsed = urlsplit(url_or_path)
    path = parsed.path or '/'
    query = parse_qs(parsed.query, keep_blank_values=False)
    filename_param = query.get('filename', [None])[0]

    inferred_type = content_type
    if inferred_type is None:
        if path.endswith('.pdf'):
            inferred_type = 'application/pdf'
        elif path.endswith('.gz'):
            inferred_type = 'application/gzip'
        elif path.endswith('.parquet'):
            inferred_type = 'application/vnd.apache.parquet'
        elif path.endswith('.json'):
            inferred_type = 'application/json; charset=utf-8'
        else:
            inferred_type = 'application/octet-stream'

    normalized_type = inferred_type.split(';', 1)[0].strip().lower()
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Expose-Headers': ', '.join(cfg['cors']['rules'][0]['expose_headers']),
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Content-Type': inferred_type,
    }

    # Chromium's built-in PDF viewer breaks if Content-Security-Policy: sandbox; default-src 'none' is sent.
    if normalized_type != 'application/pdf':
        headers['Content-Security-Policy'] = "sandbox; default-src 'none'"

    if path.startswith('/bodies/sha256/'):
        headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        disposition_kind = 'inline' if normalized_type == 'application/pdf' else 'attachment'
        headers['Content-Disposition'] = format_content_disposition(disposition_kind, filename_param)
    elif path in {'/viewer-publications/manifest.json', '/exports/manifest.json'} or (
        path.startswith('/exports/')
        and path.endswith(('/manifest.json', '/latest.json'))
        and '/releases/' not in path
        and '/snapshots/' not in path
    ):
        headers['Cache-Control'] = 'no-store'
    elif path.endswith('/recovery-status.json'):
        headers['Cache-Control'] = 'no-store'
    elif path.startswith(('/viewer-publications/', '/exports/')):
        headers['Cache-Control'] = 'public, max-age=31536000, immutable'

    return headers

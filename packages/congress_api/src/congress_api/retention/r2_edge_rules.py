"""Declarative Cloudflare R2 Custom Domain, CORS, and Response Header Transform Rule contract."""

from pathlib import Path
import json
from hashlib import sha256
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit


DEFAULT_EDGE_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / 'infra'
    / 'cloudflare'
    / 'congressional-data-r2-edge.json'
)
DEFAULT_TERRAFORM_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / 'infra'
    / 'cloudflare'
    / 'main.tf'
)

PUBLIC_HOSTNAME = 'congressional-data.spicygov.ai'
PUBLIC_BUCKET = 'congressional-tech-raw'


def load_edge_config(path=None):
    """Load the declarative Cloudflare R2 custom-domain edge configuration."""
    target = Path(path) if path is not None else DEFAULT_EDGE_CONFIG_PATH
    return json.loads(target.read_text(encoding='utf-8'))


def build_declarative_ruleset_spec(config=None, *, terraform_path=None):
    """Return the declarative Wrangler R2 CORS and Terraform cloudflare_ruleset specification."""
    cfg = config or load_edge_config()
    if 'waf_custom_rules' in cfg:
        raise ValueError('Legacy firewall path allowlist (waf_custom_rules) is retired')
    tf_target = Path(terraform_path) if terraform_path is not None else DEFAULT_TERRAFORM_CONFIG_PATH
    tf_text = tf_target.read_text(encoding='utf-8')
    if 'resource "cloudflare_ruleset" "public_r2_response_headers"' not in tf_text:
        raise ValueError('Terraform cloudflare_ruleset resource missing from infra/cloudflare/main.tf')
    if 'resource "cloudflare_r2_bucket_cors" "public_r2_cors"' not in tf_text:
        raise ValueError('Terraform cloudflare_r2_bucket_cors resource missing from infra/cloudflare/main.tf')
    configuration = body_integrity_configuration(cfg)
    if 'output "public_r2_body_integrity_rule"' not in tf_text:
        raise ValueError('Terraform single-rule integrity output is missing')
    transform = cfg['response_header_transform_rules'][0]
    ruleset = transform['ruleset']
    return {
        'custom_domain': cfg['custom_domain'],
        'r2_bucket_cors': {
            'bucket': cfg['custom_domain']['bucket'],
            'rules': cfg['cors']['rules'],
        },
        'cloudflare_configuration_rule': configuration,
        'cloudflare_ruleset': {
            'name': ruleset['name'],
            'description': transform['description'],
            'kind': ruleset['kind'],
            'phase': ruleset['phase'],
            'rules': ruleset['rules'],
        },
    }


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


def body_integrity_configuration(config=None):
    """Require the exact archive scope and only the body-mutating feature setting."""
    cfg=config or load_edge_config()
    declarations=cfg.get('configuration_rules')
    if not isinstance(declarations,list) or len(declarations)!=1:
        raise ValueError('Declare exactly one archive body integrity configuration rule')
    value=declarations[0]
    expected=f'(http.host eq "{PUBLIC_HOSTNAME}") and starts_with(http.request.uri.path, "/bodies/sha256/")'
    rule=value.get('rule') or {}
    if (cfg['custom_domain']['hostname']!=PUBLIC_HOSTNAME or value.get('phase')!='http_config_settings'
            or value.get('kind')!='zone' or value.get('deployment')!='single-rule-append-or-owned-patch'
            or rule.get('ref')!='public-r2-content-addressed-body-no-email-obfuscation'
            or rule.get('description')!='Preserve exact archived body bytes on the public R2 custom domain'
            or set(rule)!={'ref','description','expression','action','action_parameters','enabled'}
            or rule.get('expression')!=expected or rule.get('action')!='set_config'
            or set(rule.get('action_parameters') or {})!={'email_obfuscation'}
            or rule['action_parameters']['email_obfuscation'] is not False or rule.get('enabled') is not True):
        raise ValueError('Archive integrity rule must disable only email obfuscation on the exact host/body prefix')
    probe=value.get('integrity_probe') or {}
    digest=probe.get('decoded_sha256','')
    if (not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)
            or probe.get('path')!=f'/bodies/sha256/{digest[:2]}/{digest}'
            or type(probe.get('decoded_bytes')) is not int or type(probe.get('max_bytes')) is not int
            or not 0<probe['decoded_bytes']<=probe['max_bytes']<=1<<20):
        raise ValueError('Archive integrity probe needs an exact bounded content-addressed body')
    return value


def plan_body_integrity_rule(observed,zone_id,config=None):
    """Plan only one append/owned-rule PATCH from a successful provider readback.

    This function performs no HTTP writes. In particular it cannot replace a
    phase ruleset or infer empty state from a permission failure.
    """
    declaration=body_integrity_configuration(config)
    if not isinstance(zone_id,str) or not re.fullmatch('[a-f0-9]{32}',zone_id):
        raise ValueError('An exact Cloudflare zone ID is required')
    data=observed.get('data') or {}
    current=data.get('result') or {}
    if observed.get('status')!=200 or data.get('success') is not True:
        raise ValueError(f'Configuration ruleset readback must succeed; HTTP {observed.get("status")} is unknown state')
    if current.get('phase')!='http_config_settings' or current.get('kind')!='zone':
        raise ValueError('Observed ruleset is not the zone configuration entrypoint')
    ruleset_id=current.get('id','');rules=current.get('rules')
    if not isinstance(ruleset_id,str) or not re.fullmatch('[a-f0-9]{32}',ruleset_id) or not isinstance(rules,list):
        raise ValueError('Observed configuration ruleset has no valid identity/rules')
    ids=[r.get('id','') for r in rules];refs=[r['ref'] for r in rules if r.get('ref')]
    if (any(not isinstance(i,str) or not re.fullmatch('[a-f0-9]{32}',i) for i in ids) or len(set(ids))!=len(ids)
            or len(set(refs))!=len(refs)):
        raise ValueError('Observed rules contain duplicate refs/IDs or invalid identity')
    desired=declaration['rule']
    if any(r.get('description')==desired['description'] and r.get('ref')!=desired['ref'] for r in rules):
        raise ValueError('Description-only match requires manual ownership review; an exact owned ref is required for PATCH')
    owned=[r for r in rules if r.get('ref')==desired['ref']]
    if len(owned)>1:raise ValueError('Owned archive rule is ambiguous; preserve all rules for review')
    existing=owned[0] if owned else None
    if existing and (existing.get('action')!='set_config' or set(existing.get('action_parameters') or {})-{'email_obfuscation'}):
        raise ValueError('Matching rule also owns other settings; do not overwrite it')
    unrelated=[r for r in rules if r is not existing]
    base=f'/zones/{zone_id}/rulesets/{ruleset_id}/rules'
    operations=[]
    if (not existing or any(existing.get(k)!=v for k,v in desired.items())
            or (existing.get('action_parameters') or {}).get('email_obfuscation') is not False
            or rules[-1] is not existing):
        body=dict(desired)
        if unrelated:body['position']={'after':unrelated[-1]['id']}
        operations=[dict(method='PATCH' if existing else 'POST',path=base+('/'+existing['id'] if existing else ''),body=body)]
    return dict(phase='http_config_settings',zone_id=zone_id,ruleset_id=ruleset_id,
        observed_version=current.get('version'),operations=operations,
        owned_rule_id=existing['id'] if existing else None,
        preserve_unrelated_rule_ids=[r['id'] for r in unrelated],
        unrelated_rules_sha256=sha256(json.dumps(unrelated,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        instruction='Read the phase again before applying; append or patch only the verified owned rule last. Never PUT the phase ruleset.')

import {useState} from 'react';

export function releaseParquetBase(rawBase: string | undefined, releaseId: string | undefined): string {
  const origin = rawBase && /^https?:\/\//i.test(rawBase)
    ? rawBase.replace(/\/+$/, '') + '/'
    : 'https://congressional-data.spicygov.ai/';
  const rel = releaseId || '<release_id>';
  try {
    return new URL(`viewer-publications/releases/${rel}/`, origin).href;
  } catch {
    return `https://congressional-data.spicygov.ai/viewer-publications/releases/${rel}/`;
  }
}

export function buildCitableDuckDbSql(props: {
  kind: 'document' | 'hearing' | 'organization';
  releaseId?: string;
  rawBase?: string;
  linkKey?: string;
  eventId?: string | number;
  orgId?: string;
}): string {
  const base = releaseParquetBase(props.rawBase, props.releaseId);
  if (props.kind === 'document') {
    const key = String(props.linkKey || '<link_key>').toLowerCase();
    return [
      'SELECT l.list_row, l.filename, l.title, lower(hex(d.link_key)) AS link_key, lower(hex(d.saved_body)) AS saved_body_sha256',
      `FROM read_parquet('${base}list.parquet') l`,
      `JOIN read_parquet('${base}detail.parquet') d USING (list_row)`,
      `WHERE lower(hex(d.link_key)) = '${key}';`,
    ].join('\n');
  }
  if (props.kind === 'hearing') {
    const ev = String(props.eventId ?? '<event_id>').trim();
    const where = /^\d+$/.test(ev) ? `event_id = ${ev}` : `cast(event_id AS VARCHAR) = '${ev.replace(/'/g, "''")}'`;
    return [
      'SELECT event_id, title, meeting_date, chamber, status',
      `FROM read_parquet('${base}meetings.parquet')`,
      `WHERE ${where};`,
    ].join('\n');
  }
  const org = String(props.orgId || '<org_id>').toLowerCase().replace(/'/g, "''");
  return [
    'SELECT org_id, display_name, kind, taxonomy_parent, taxonomy_category, appearance_count',
    `FROM read_parquet('${base}organizations.parquet')`,
    `WHERE org_id = '${org}';`,
  ].join('\n');
}

export function CitableReceipt({
  kind,
  releaseId,
  rawBase,
  linkKey,
  savedBodySha256,
  eventId,
  orgId,
}: {
  kind: 'document' | 'hearing' | 'organization';
  releaseId?: string;
  rawBase?: string;
  linkKey?: string;
  savedBodySha256?: string | null;
  eventId?: string | number;
  orgId?: string;
}) {
  const [copied, setCopied] = useState<'' | 'sql' | 'json'>('');
  const cleanLinkKey = linkKey ? String(linkKey).toLowerCase() : undefined;
  const cleanSha = savedBodySha256 ? String(savedBodySha256).toLowerCase() : null;
  const canonicalId = kind === 'document' ? cleanLinkKey : kind === 'hearing' ? (eventId != null ? String(eventId) : undefined) : orgId;
  if (!canonicalId && !releaseId) return null;

  const sql = buildCitableDuckDbSql({kind, releaseId, rawBase, linkKey: cleanLinkKey, eventId, orgId});
  const receiptPayload = JSON.stringify({
    kind,
    release_id: releaseId ?? null,
    ...(kind === 'document' ? {link_key: cleanLinkKey ?? null, saved_body_sha256: cleanSha} : {}),
    ...(kind === 'hearing' ? {event_id: eventId != null ? String(eventId) : null} : {}),
    ...(kind === 'organization' ? {org_id: orgId ?? null} : {}),
    duckdb_sql: sql,
  }, null, 2);

  async function copy(text: string, mode: 'sql' | 'json') {
    try {
      await navigator.clipboard?.writeText(text);
      setCopied(mode);
      setTimeout(() => setCopied(cur => (cur === mode ? '' : cur)), 2000);
    } catch {
      // Clipboard API may be unavailable in restricted contexts; the drawer remains inspectable.
    }
  }

  const idLabel = kind === 'document' ? 'link_key' : kind === 'hearing' ? 'event_id' : 'org_id';

  return <div className="archive-receipt-block" data-citable-receipt={kind}>
    <div className="archive-receipt-bar">
      <span className="archive-receipt-title">Citable Receipt</span>
      <div className="archive-pill-list">
        <button type="button" className="archive-measure-pill" onClick={() => copy(sql, 'sql')}>
          {copied === 'sql' ? 'Copied DuckDB SQL' : 'Copy DuckDB SQL'}
        </button>
        <button type="button" className="archive-measure-pill" onClick={() => copy(receiptPayload, 'json')}>
          {copied === 'json' ? 'Copied Receipt' : 'Copy Receipt JSON'}
        </button>
      </div>
    </div>
    <details className="archive-receipt-drawer">
      <summary>Immutable release &amp; DuckDB verification query</summary>
      <dl className="archive-provenance-meta">
        <div>
          <dt>release_id</dt>
          <dd><code>{releaseId || 'Unavailable in this view'}</code></dd>
        </div>
        {canonicalId && <div>
          <dt>{idLabel}</dt>
          <dd><code>{canonicalId}</code></dd>
        </div>}
        {kind === 'document' && <div>
          <dt>saved_body_sha256</dt>
          <dd>{cleanSha ? <code>{cleanSha}</code> : 'Unavailable in this release'}</dd>
        </div>}
      </dl>
      <pre className="archive-receipt-sql"><code>{sql}</code></pre>
    </details>
  </div>;
}

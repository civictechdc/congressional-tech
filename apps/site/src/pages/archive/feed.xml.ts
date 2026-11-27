import type {APIRoute} from 'astro';

const releaseFiles = import.meta.glob('../../../../../docs/releases/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function escapeXml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

interface ReleaseNoteEntry {
  filename: string;
  date: string;
  shortId: string;
  releaseId: string;
  linksSummary: string;
  changesSummary: string;
}

function parseReleaseNotes(): ReleaseNoteEntry[] {
  return Object.entries(releaseFiles)
    .map(([filePath, text]) => {
      const filename = filePath.split('/').pop() ?? '';
      const match = /^(\d{4}-\d{2}-\d{2})-([0-9a-f]{12})\.md$/i.exec(filename);
      if (!match) return null;
      const date = match[1];
      const shortId = match[2];
      const releaseMatch = /- Release:\s*`([0-9a-f]{64})`/i.exec(text);
      const releaseId = releaseMatch ? releaseMatch[1] : shortId;
      const linksMatch = /## Links\s+([\s\S]*?)(?:\n## |\n*$)/.exec(text);
      const linksSummary = linksMatch
        ? linksMatch[1].trim().split(/\n\s*\n|\n\|/)[0].trim().replace(/\s+/g, ' ')
        : '';
      const rowChanges = [...text.matchAll(/^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|[^|]*\|\s*(-?\d+)\s*\|/gm)]
        .slice(0, 5)
        .map(m => `${m[1]} (${m[2].trim()}: ${m[3]})`);
      const changesSummary = rowChanges.length ? `Row changes: ${rowChanges.join('; ')}` : '';
      return {filename, date, shortId, releaseId, linksSummary, changesSummary};
    })
    .filter((entry): entry is ReleaseNoteEntry => entry !== null)
    .sort((a, b) => b.filename.localeCompare(a.filename))
    .slice(0, 20);
}

export const GET: APIRoute = ({site}) => {
  const baseOrigin = (site?.toString() || 'https://civictechdc.github.io').replace(/\/+$/, '');
  const archiveUrl = `${baseOrigin}/congressional-tech/archive/?tab=accountability`;
  const feedUrl = `${baseOrigin}/congressional-tech/archive/feed.xml`;
  const entries = parseReleaseNotes();
  const updated = entries[0] ? `${entries[0].date}T00:00:00Z` : '2026-11-27T00:00:00Z';

  const xmlEntries = entries.map(entry => {
    const summary = [
      `Release ${entry.releaseId}.`,
      entry.linksSummary,
      entry.changesSummary,
    ].filter(Boolean).join(' ');
    const entryHref = `${archiveUrl}&q=${encodeURIComponent(entry.shortId)}`;
    return [
      '  <entry>',
      `    <title>${escapeXml(`Archive release ${entry.shortId} (${entry.date})`)}</title>`,
      `    <id>${escapeXml(`urn:congressional-tech:release:${entry.releaseId}`)}</id>`,
      `    <updated>${escapeXml(`${entry.date}T00:00:00Z`)}</updated>`,
      `    <link rel="alternate" type="text/html" href="${escapeXml(entryHref)}" />`,
      `    <summary>${escapeXml(summary)}</summary>`,
      '  </entry>',
    ].join('\n');
  }).join('\n');

  const body = [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<feed xmlns="http://www.w3.org/2005/Atom">',
    '  <title>Congress Explorer — Accountability &amp; Release Churn</title>',
    '  <subtitle>Published archive releases, link redirects, and removal notices from Congressional Tech.</subtitle>',
    `  <id>${escapeXml(feedUrl)}</id>`,
    `  <updated>${escapeXml(updated)}</updated>`,
    `  <link rel="self" type="application/atom+xml" href="${escapeXml(feedUrl)}" />`,
    `  <link rel="alternate" type="text/html" href="${escapeXml(archiveUrl)}" />`,
    xmlEntries,
    '</feed>',
    '',
  ].join('\n');

  return new Response(body, {
    headers: {
      'Content-Type': 'application/atom+xml; charset=utf-8',
    },
  });
};

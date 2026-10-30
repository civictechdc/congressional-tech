import test from 'node:test';
import assert from 'node:assert/strict';
import {
  savedOriginalUrl,
  sourceFacts,
  sourceLinks,
  presentRecord,
} from './record-presentation.ts';

test('savedOriginalUrl handles valid, malformed, and adversarial inputs', () => {
  // Nullish and non-object inputs
  assert.equal(savedOriginalUrl(null), undefined);
  assert.equal(savedOriginalUrl(undefined), undefined);
  assert.equal(savedOriginalUrl('string'), undefined);
  assert.equal(savedOriginalUrl(123), undefined);
  assert.equal(savedOriginalUrl({}), undefined);

  // Missing or empty retained_uri
  assert.equal(savedOriginalUrl({ retained_uri: null }), undefined);
  assert.equal(savedOriginalUrl({ retained_uri: undefined }), undefined);
  assert.equal(savedOriginalUrl({ retained_uri: '' }), undefined);
  assert.equal(savedOriginalUrl({ retained_uri: '   ' }), undefined);
  assert.equal(savedOriginalUrl({ retained_uri: 12345 }), undefined);

  // Valid relative CAS URI
  assert.equal(
    savedOriginalUrl({ retained_uri: 'bodies/sha256/ab/abcdef0123456789.gz' }),
    '/bodies/sha256/ab/abcdef0123456789.gz'
  );

  // Valid absolute path CAS URI
  assert.equal(
    savedOriginalUrl({ retained_uri: '/bodies/sha256/ab/abcdef0123456789.pdf' }),
    '/bodies/sha256/ab/abcdef0123456789.pdf'
  );

  // Valid HTTPS URI
  assert.equal(
    savedOriginalUrl({ retained_uri: 'https://r2.example.com/bodies/sha256/ab/abcdef0123456789.gz' }),
    'https://r2.example.com/bodies/sha256/ab/abcdef0123456789.gz'
  );

  // Malformed: javascript: pseudo-protocol
  assert.equal(savedOriginalUrl({ retained_uri: 'javascript:alert(1)' }), undefined);

  // Malformed: file: URI
  assert.equal(savedOriginalUrl({ retained_uri: 'file:///etc/passwd' }), undefined);

  // Protocol-relative URI check:
  // Protocol-relative URLs starting with // must be rejected to prevent open redirects.
  const protoRelative = savedOriginalUrl({ retained_uri: '//evil.com/malicious' });
  assert.equal(protoRelative, undefined, 'Rejects protocol-relative URL');
});

test('sourceFacts handles normalized schema without payload, empty arrays, and null values', () => {
  // Completely bare source record
  const bare = sourceFacts({ kind: 'source_record', id: 'src-1' });
  assert.ok(Array.isArray(bare));

  // Normalized record with typed columns and NO payload
  const normalized = sourceFacts({
    kind: 'source_record',
    id: 'src-2',
    provider: 'congress.gov',
    retrieved_at: '2026-10-22T15:00:00Z',
    retained_uri: 'bodies/sha256/12/1234567890abcdef.gz',
    retained_sha256: '1234567890abcdef',
    identifier_scheme: 'congress.gov:event',
    identifier_value: '119575',
    identifier_scope: 'house',
    facts: [
      { label: 'Chamber', value: 'House' },
      { label: 'Event ID', value: '119575' },
    ],
    links: [],
  });
  assert.ok(Array.isArray(normalized));
  assert.ok(normalized.some(([label, value]) => label === 'Source' && value === 'congress.gov'));
  assert.ok(!normalized.some(([label]) => label === 'Saved original'));
  assert.ok(normalized.some(([label, value]) => label === 'Chamber' && value === 'House'));
  assert.ok(normalized.some(([label, value]) => label === 'Event ID' && value === '119575'));

  // Edge case: facts array is empty facts: []
  const emptyFacts = sourceFacts({
    kind: 'source_record',
    id: 'src-3',
    facts: [],
  });
  assert.ok(Array.isArray(emptyFacts));

  // Edge case: facts contains null or malformed items
  const malformedFacts = sourceFacts({
    kind: 'source_record',
    id: 'src-4',
    facts: [
      null,
      undefined,
      { label: null, value: 'bad label' },
      { label: 'bad value', value: null },
      { label: 'Valid', value: 'Good' },
    ] as unknown as { label: string; value: string }[],
  });
  assert.ok(Array.isArray(malformedFacts));
  assert.ok(malformedFacts.some(([l, v]) => l === 'Valid' && v === 'Good'));
});

test('sourceLinks handles normalized schema without payload and empty arrays', () => {
  // Bare record
  const bare = sourceLinks({ kind: 'source_record', id: 'src-1' });
  assert.deepEqual(bare, { links: [] });

  // Record with empty links: []
  const empty = sourceLinks({ kind: 'source_record', id: 'src-2', links: [] });
  assert.deepEqual(empty, { links: [] });

  // Record with populated normalized links
  const populated = sourceLinks({
    kind: 'source_record',
    id: 'src-3',
    links: [
      { group: 'Source', label: 'Original Page', href: 'https://example.com/page' },
      { group: 'Document', label: 'PDF Version', href: 'https://example.com/doc.pdf' },
    ],
  });
  assert.equal(populated.links.length, 2);
  assert.equal(populated.links[0].label, 'Original Page');
  assert.equal(populated.links[1].href, 'https://example.com/doc.pdf');
});

test('presentRecord handles source_record and missing attributes cleanly', () => {
  const src = {
    kind: 'source_record' as const,
    id: 'src-01',
    title: 'Clean Source Title',
  };
  const presented = presentRecord(src as any);
  assert.equal(presented.id, 'src-01');
  assert.equal(presented.title, 'Clean Source Title');
});

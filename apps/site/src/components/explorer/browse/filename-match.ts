function httpUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function fields(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** URLs and saved-copy digests a material can join to the filename catalog. */
export function catalogMatchFiles(record: unknown): { url?: string; saved_copy_sha256?: string }[] {
  const row = fields(record);
  const files = Array.isArray(row.files) ? row.files : [];
  const items = files.flatMap(file => {
    const value = fields(file);
    const url = httpUrl(value.url);
    const sha = typeof value.saved_copy_sha256 === 'string' ? value.saved_copy_sha256 : '';
    if (!url && !sha) return [];
    return [{ ...(url ? { url } : {}), ...(sha ? { saved_copy_sha256: sha } : {}) }];
  });
  const recording = httpUrl(row.recording_url);
  if (recording && !items.some(item => item.url === recording)) items.push({ url: recording });
  return items;
}

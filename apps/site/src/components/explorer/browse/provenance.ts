export function validUrl(value: unknown): URL | null {
  if (typeof value !== 'string' && !(value instanceof URL)) return null;
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

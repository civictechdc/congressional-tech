/** Base-aware URL helper. BASE_URL is '/congressional-tech/' in production. */
const base = import.meta.env.BASE_URL.replace(/\/+$/, '');

export function withBase(path: string): string {
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

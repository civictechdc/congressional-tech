/** Page numbers and filename dates shared by the catalog reader and the materials workspace. */
export function positiveInteger(value: unknown, fallback = 1, maximum = Number.MAX_SAFE_INTEGER): number {
  const number = Number(value);
  return Number.isFinite(number) && number >= 1 ? Math.min(maximum, Math.floor(number)) : fallback;
}

export function filenameDate(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value + 'T00:00:00Z');
  if (Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== value) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'long', timeZone: 'UTC' }).format(date);
}

// Positive finite values round down and clamp; invalid/nonpositive values use
// the stated default. A page cannot exceed the known page count.
export function positiveInteger(value, fallback = 1, maximum = Number.MAX_SAFE_INTEGER) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 1 ? Math.min(maximum, Math.floor(number)) : fallback;
}
export function filenameDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value + 'T00:00:00Z');
  if (Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== value) return value;
  return new Intl.DateTimeFormat(undefined, {dateStyle: 'long', timeZone: 'UTC'}).format(date);
}

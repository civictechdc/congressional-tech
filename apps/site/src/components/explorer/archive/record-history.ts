// Congresses before the 74th began March 4; each endpoint follows its own rule.
// https://www.senate.gov/legislative/DatesofSessionsofCongress.htm
export function congressPeriod(congress: number) {
  const start = (number: number) => `${1789 + (number - 1) * 2}-${number < 74 ? '03-04' : '01-03'}`;
  return { start: start(congress), end: start(congress + 1) };
}

const day = (value: any) => value instanceof Date ? value.toISOString().slice(0, 10)
  : value == null ? null : String(value).slice(0, 10);

export function resolveCommitteeName(committee: any, dateOrCongress?: string | number | Date | null): string {
  if (!committee) return '';
  const history = committee.names ?? [];
  if (dateOrCongress != null) {
    const raw = String(dateOrCongress).trim();
    if (/^[1-9]\d{0,2}$/.test(raw)) {
      const period = congressPeriod(Number(raw));
      for (const name of history) {
        const start = day(name.start), end = day(name.end);
        if ((!start || start < period.end) && (!end || end > period.start) && name.name) return name.name;
      }
    } else {
      const target = day(dateOrCongress);
      for (const name of history) {
        const start = day(name.start), end = day(name.end);
        if (target && (!start || target >= start) && (!end || target < end) && name.name) return name.name;
      }
    }
  }
  return committee.name ?? '';
}

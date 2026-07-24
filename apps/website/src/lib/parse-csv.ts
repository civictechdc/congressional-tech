/**
 * Minimal CSV parser.
 *
 * Parses a CSV string into an array of row objects keyed by the header row.
 * Handles quoted fields (`"a,b"`) and escaped quotes (`""`), CRLF/CR line
 * endings, and skips blank lines. Values are trimmed.
 *
 * Every value is returned as a string; callers are responsible for coercing
 * numeric/enum columns (see parseRow in use-youtube-event-id-report.tsx).
 */
export function parseCSV(text: string): Record<string, string>[] {
    const lines = text
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
        .split("\n")
        .filter((line) => line.trim() !== "");

    if (lines.length === 0) return [];

    const headers = splitLine(lines[0]);

    return lines.slice(1).map((line) => {
        const values = splitLine(line);
        const row: Record<string, string> = {};
        headers.forEach((header, i) => {
            row[header] = values[i] ?? "";
        });
        return row;
    });
}

/** Split a single CSV line into trimmed fields, respecting quotes. */
function splitLine(line: string): string[] {
    const fields: string[] = [];
    let current = "";
    let inQuotes = false;

    for (let i = 0; i < line.length; i++) {
        const char = line[i];

        if (inQuotes) {
            if (char === '"') {
                if (line[i + 1] === '"') {
                    current += '"';
                    i++;
                } else {
                    inQuotes = false;
                }
            } else {
                current += char;
            }
        } else if (char === '"') {
            inQuotes = true;
        } else if (char === ",") {
            fields.push(current);
            current = "";
        } else {
            current += char;
        }
    }
    fields.push(current);

    return fields.map((field) => field.trim());
}

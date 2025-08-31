export function parseCSV(text: string): Array<Record<string, string>> {
    const rows: string[][] = [];
    let field = "";
    let row: string[] = [];
    let inQuotes = false;

    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (inQuotes) {
            if (c === '"') {
                if (text[i + 1] === '"') {
                    field += '"';
                    i++;
                } else {
                    inQuotes = false;
                }
            } else {
                field += c;
            }
        } else {
            if (c === '"') {
                inQuotes = true;
            } else if (c === ",") {
                row.push(field);
                field = "";
            } else if (c === "\n") {
                row.push(field);
                rows.push(row);
                row = [];
                field = "";
            } else if (c === "\r") {
                // ignore
            } else {
                field += c;
            }
        }
    }
    if (field.length > 0 || row.length > 0) {
        row.push(field);
        rows.push(row);
    }

    const nonEmpty = rows.filter((r) => r.length && !(r.length === 1 && r[0].trim() === ""));
    if (nonEmpty.length === 0) return [];

    const header = nonEmpty[0];
    return nonEmpty.slice(1).map((r) => {
        const obj: Record<string, string> = {};
        for (let j = 0; j < header.length; j++) {
            obj[header[j]] = r[j] ?? "";
        }
        return obj;
    });
}

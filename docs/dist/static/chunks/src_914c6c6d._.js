(globalThis.TURBOPACK || (globalThis.TURBOPACK = [])).push([typeof document === "object" ? document.currentScript : undefined,
"[project]/src/lib/parse-csv.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "parseCSV",
    ()=>parseCSV
]);
function parseCSV(text) {
    const rows = [];
    let field = "";
    let row = [];
    let inQuotes = false;
    for(let i = 0; i < text.length; i++){
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
    const nonEmpty = rows.filter((r)=>r.length && !(r.length === 1 && r[0].trim() === ""));
    if (nonEmpty.length === 0) return [];
    const header = nonEmpty[0];
    return nonEmpty.slice(1).map((r)=>{
        const obj = {};
        for(let j = 0; j < header.length; j++){
            var _r_j;
            obj[header[j]] = (_r_j = r[j]) !== null && _r_j !== void 0 ? _r_j : "";
        }
        return obj;
    });
}
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/hooks/use-youtube-event-id-report.tsx [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>__TURBOPACK__default__export__,
    "fetchYoutubeEventIdReport",
    ()=>fetchYoutubeEventIdReport,
    "useYoutubeEventIdReport",
    ()=>useYoutubeEventIdReport
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$parse$2d$csv$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/lib/parse-csv.ts [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f40$tanstack$2f$react$2d$query$2f$build$2f$modern$2f$useQuery$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/@tanstack/react-query/build/modern/useQuery.js [app-client] (ecmascript)");
var _s = __turbopack_context__.k.signature();
;
;
function parseRow(d) {
    return {
        committee_name: d.committee_name,
        handle: d.handle,
        total_videos: Number(d.total_videos),
        missing_event_id: Number(d.missing_event_id),
        congress_number: Number(d.congress_number),
        control: d.control,
        chamber: d.chamber
    };
}
async function fetchYoutubeEventIdReport() {
    const res = await fetch("/public/data/youtube/youtube_event_id_report.csv");
    if (!res.ok) {
        throw new Error("Failed to fetch CSV: ".concat(res.status, " ").concat(res.statusText));
    }
    const text = await res.text();
    const rows = (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$parse$2d$csv$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["parseCSV"])(text);
    return rows.map(parseRow);
}
function useYoutubeEventIdReport() {
    _s();
    return (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f40$tanstack$2f$react$2d$query$2f$build$2f$modern$2f$useQuery$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useQuery"])({
        queryKey: [
            "youtubeEventIdReport"
        ],
        queryFn: fetchYoutubeEventIdReport,
        staleTime: 5 * 60 * 1000
    });
}
_s(useYoutubeEventIdReport, "4ZpngI1uv+Uo3WQHEZmTQ5FNM+k=", false, function() {
    return [
        __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f40$tanstack$2f$react$2d$query$2f$build$2f$modern$2f$useQuery$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useQuery"]
    ];
});
const __TURBOPACK__default__export__ = useYoutubeEventIdReport;
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/components/dashboard/dashboard-content.tsx [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "DashboardContent",
    ()=>DashboardContent
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/compiled/react/jsx-dev-runtime.js [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$use$2d$youtube$2d$event$2d$id$2d$report$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/hooks/use-youtube-event-id-report.tsx [app-client] (ecmascript)");
;
var _s = __turbopack_context__.k.signature();
"use client";
;
function DashboardContent(param) {
    let {} = param;
    _s();
    const data = (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$use$2d$youtube$2d$event$2d$id$2d$report$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"])();
    console.log(data);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {}, void 0, false, {
        fileName: "[project]/src/components/dashboard/dashboard-content.tsx",
        lineNumber: 7,
        columnNumber: 12
    }, this);
}
_s(DashboardContent, "yKwvZgYFSsXOmbz3XDKK1QinxkY=", false, function() {
    return [
        __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$use$2d$youtube$2d$event$2d$id$2d$report$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"]
    ];
});
_c = DashboardContent;
var _c;
__turbopack_context__.k.register(_c, "DashboardContent");
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
]);

//# sourceMappingURL=src_914c6c6d._.js.map
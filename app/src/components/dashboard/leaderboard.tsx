import React, { useMemo, useState } from "react";

import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { cn } from "@/lib/utils";
import { Switch } from "../ui/switch";
import { Label } from "../ui/label";
import { CircleCheck, CircleX } from "lucide-react";

// Derived row type with helpful fields
type Row = {
    handle: string;
    committee: string;
    total: number;
    missing: number;
    have: number;
    frac: number; // fraction WITH event IDs
};

type Mode = "percent" | "count"; // percent = by fraction; count = by absolute numbers

type Variant = "best" | "worst"; // best = higher is better; worst = lower fraction / higher missing

function buildRows(congressData: YoutubeEventIdRow[]): Row[] {
    return congressData
        .filter((r) => r.total_videos > 0)
        .map((r) => ({
            handle: r.handle,
            committee: r.committee_name,
            total: r.total_videos,
            missing: r.missing_event_id,
            have: r.total_videos - r.missing_event_id,
            frac: (r.total_videos - r.missing_event_id) / r.total_videos,
        }));
}

function formatPercent(x: number): string {
    return `${(x * 100).toFixed(1)}%`;
}

function sortRows(rows: Row[], variant: Variant, mode: Mode): Row[] {
    const copy = [...rows];
    if (variant === "best" && mode === "percent") {
        // Highest fraction first; tie-break by total
        copy.sort((a, b) => b.frac - a.frac || b.total - a.total);
    } else if (variant === "best" && mode === "count") {
        // Highest absolute HAVE count first; tie-break by total
        copy.sort((a, b) => b.have - a.have || b.total - a.total);
    } else if (variant === "worst" && mode === "percent") {
        // Lowest fraction first; tie-break by missing desc, then total
        copy.sort((a, b) => a.frac - b.frac || b.missing - a.missing || b.total - a.total);
    } else {
        // worst + count => most MISSING first; tie-break by total
        copy.sort((a, b) => b.missing - a.missing || b.total - a.total);
    }
    return copy;
}

function Metric({ row, variant, mode }: { row: Row; variant: Variant; mode: Mode }) {
    const isBest = variant === "best";

    // Values
    const pctHave = row.frac; // have / total
    const pctMissing = 1 - row.frac; // missing / total
    const haveFrac = `${row.have}/${row.total}`;
    const missFrac = `${row.missing}/${row.total}`;

    // Choose which numbers to display for this variant
    const pct = isBest ? pctHave : pctMissing;
    const frac = isBest ? haveFrac : missFrac;

    // When mode === 'count', show fraction as primary; otherwise percent primary.
    const primary = mode === "count" ? frac : `${formatPercent(pct)}`;
    const secondary = mode === "count" ? `${formatPercent(pct)}` : frac;

    return (
        <div className="text-right">
            {/* Primary row with fixed-width number and icon to the right */}
            <div className="flex items-center justify-end gap-2">
                <span className="min-w-[10ch] text-right leading-none font-semibold tabular-nums">
                    {primary}
                </span>
                {isBest ? (
                    <CircleCheck className="text-success h-4 w-4 shrink-0" />
                ) : (
                    <CircleX className="text-destructive h-4 w-4 shrink-0" />
                )}
            </div>
            {/* Secondary row */}
            <div className="text-muted-foreground text-xs leading-tight tabular-nums">
                {secondary}
            </div>
        </div>
    );
}

function LeaderboardSection({
    title,
    rows,
    variant,
    className,
}: {
    title: string;
    rows: Row[];
    variant: Variant;
    className?: string;
}) {
    const [mode, setMode] = useState<Mode>("percent");
    const top = useMemo(() => sortRows(rows, variant, mode), [rows, variant, mode]);

    return (
        <section
            className={cn(
                "flex h-full max-h-full min-h-0 flex-1 flex-col overflow-hidden",
                className
            )}
        >
            <CardHeader className="flex shrink-0 flex-row items-center justify-between gap-2 p-0">
                <CardTitle>{title}</CardTitle>
                <div className="flex items-center gap-2">
                    <Label
                        htmlFor={`${title}-toggle`}
                        className="text-muted-foreground text-xs whitespace-nowrap"
                    >
                        {mode === "percent" ? "Percent" : "Count"}
                    </Label>
                    <Switch
                        id={`${title}-toggle`}
                        checked={mode === "count"}
                        onCheckedChange={(checked) => setMode(checked ? "count" : "percent")}
                        aria-label="Toggle between percent and count"
                    />
                </div>
            </CardHeader>
            <hr className="my-2 shrink-0" />
            <div className="min-h-0 flex-1 overflow-y-auto">
                <ol className="space-y-2">
                    {top.map((r, i) => (
                        <Card
                            key={`${variant}-${mode}-${r.handle}`}
                            className="transition-translate p-2 duration-300 hover:-translate-y-2"
                        >
                            <CardContent className="flex items-center justify-between rounded-md">
                                <div className="min-w-0">
                                    <div className="truncate font-medium">
                                        {i + 1}. {r.handle}
                                    </div>
                                    <div className="text-muted-foreground truncate text-xs">
                                        {r.committee}
                                    </div>
                                </div>
                                <Metric row={r} variant={variant} mode={mode} />
                            </CardContent>
                        </Card>
                    ))}
                </ol>
            </div>
        </section>
    );
}

export function Leaderboard({
    congressData,
    className = "",
}: {
    congressData: YoutubeEventIdRow[];
    className?: string;
}) {
    const rows = useMemo(() => buildRows(congressData), [congressData]);

    return (
        <Card
            className={cn(
                "flex h-full max-h-full min-h-0 flex-1 flex-col overflow-hidden",
                className
            )}
        >
            <CardContent className="flex h-full max-h-full min-h-0 flex-1 overflow-hidden">
                <div className="grid h-full max-h-full min-h-0 flex-1 grid-cols-1 gap-6 overflow-hidden md:grid-cols-2">
                    <LeaderboardSection title="Best Performers" rows={rows} variant="best" />
                    <LeaderboardSection title="Worst Performers" rows={rows} variant="worst" />
                </div>
            </CardContent>
        </Card>
    );
}

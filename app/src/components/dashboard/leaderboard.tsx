import React, { useMemo, useState } from "react";

import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { cn } from "@/lib/utils";
import { Switch } from "../ui/switch";
import { Label } from "../ui/label";

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

function MetricBlock({ row, mode }: { row: Row; mode: Mode }) {
    return (
        <div className="text-right">
            {mode === "percent" ? (
                <>
                    <div className="font-medium">{formatPercent(row.frac)}</div>
                    <div className="text-muted-foreground text-xs">
                        {row.have}/{row.total}
                    </div>
                </>
            ) : (
                <>
                    <div className="font-medium">{row.have.toLocaleString()}</div>
                    <div className="text-muted-foreground text-xs">
                        with IDs of {row.total.toLocaleString()}
                    </div>
                </>
            )}
        </div>
    );
}

function MetricBlockWorst({ row, mode }: { row: Row; mode: Mode }) {
    return (
        <div className="text-right">
            {mode === "percent" ? (
                <>
                    <div className="font-medium">{formatPercent(1 - row.frac)}</div>
                    <div className="text-muted-foreground text-xs">missing fraction</div>
                </>
            ) : (
                <>
                    <div className="font-medium">{row.missing.toLocaleString()}</div>
                    <div className="text-muted-foreground text-xs">
                        missing of {row.total.toLocaleString()}
                    </div>
                </>
            )}
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
        <section className={cn(className)}>
            <CardHeader className="flex flex-row items-center justify-between gap-2 p-0 pb-2">
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
            <hr className="mb-2" />
            <div className="max-h-96 overflow-y-auto">
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
                                {variant === "best" ? (
                                    <MetricBlock row={r} mode={mode} />
                                ) : (
                                    <MetricBlockWorst row={r} mode={mode} />
                                )}
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
        <Card className={cn(className)}>
            <CardContent className="flex-1">
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                    <LeaderboardSection title="Best Performers" rows={rows} variant="best" />
                    <LeaderboardSection title="Worst Performers" rows={rows} variant="worst" />
                </div>
            </CardContent>
        </Card>
    );
}

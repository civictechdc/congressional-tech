import React from "react";

import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { cn } from "@/lib/utils";

export function Leaderboard({
    congressData,
    className = "",
}: {
    congressData: YoutubeEventIdRow[];
    className?: string;
}) {
    const rows = congressData.filter((r) => r.total_videos > 0);

    const topByFraction = [...rows]
        .map((r) => ({
            handle: r.handle,
            committee: r.committee_name,
            total: r.total_videos,
            missing: r.missing_event_id,
            have: r.total_videos - r.missing_event_id,
            frac: (r.total_videos - r.missing_event_id) / r.total_videos,
        }))
        .sort((a, b) => b.frac - a.frac || b.total - a.total)
        .slice(0, 5);

    const topByMissing = [...rows]
        .map((r) => ({
            handle: r.handle,
            committee: r.committee_name,
            total: r.total_videos,
            missing: r.missing_event_id,
            have: r.total_videos - r.missing_event_id,
            frac: (r.total_videos - r.missing_event_id) / r.total_videos,
        }))
        .sort((a, b) => b.missing - a.missing || b.total - a.total)
        .slice(0, 5);

    const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

    return (
        <Card className={cn(className)}>
            <CardContent className="flex-1">
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                    <section>
                        <CardHeader>
                            <CardTitle>Top 5 by % in Compliance</CardTitle>
                        </CardHeader>
                        <hr className="mb-2" />
                        <ol className="space-y-2">
                            {topByFraction.map((r, i) => (
                                <Card
                                    key={`frac-${r.handle}`}
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
                                        <div className="text-right">
                                            <div className="font-medium">{pct(r.frac)}</div>
                                            <div className="text-muted-foreground text-xs">
                                                {r.have}/{r.total}
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            ))}
                        </ol>
                    </section>

                    <section>
                        <CardHeader>
                            <CardTitle>Top 5 Worst Offenders by Volume</CardTitle>
                        </CardHeader>
                        <hr className="mb-2" />
                        <ol className="space-y-2">
                            {topByMissing.map((r, i) => (
                                <Card
                                    key={`miss-${r.handle}`}
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
                                        <div className="text-right">
                                            <div className="font-medium">
                                                {r.missing.toLocaleString()}
                                            </div>
                                            <div className="text-muted-foreground text-xs whitespace-nowrap">
                                                of {r.total.toLocaleString()}
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            ))}
                        </ol>
                    </section>
                </div>
            </CardContent>
        </Card>
    );
}

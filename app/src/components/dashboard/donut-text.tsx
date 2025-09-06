"use client";

import { TrendingUp } from "lucide-react";
import { Label, Pie, PieChart } from "recharts";

import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";

import colors from "tailwindcss/colors";

import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import {
    ChartConfig,
    ChartContainer,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

export const description = "A donut chart with text";

const chartConfig = {
    visitors: {
        label: "Visitors",
    },
    chrome: {
        label: "Chrome",
        color: "var(--chart-1)",
    },
    safari: {
        label: "Safari",
        color: "var(--chart-2)",
    },
    firefox: {
        label: "Firefox",
        color: "var(--chart-3)",
    },
    edge: {
        label: "Edge",
        color: "var(--chart-4)",
    },
    other: {
        label: "Other",
        color: "var(--chart-5)",
    },
} satisfies ChartConfig;

export function ChartPieDonutText({
    congressData,
    className = "",
}: {
    congressData: YoutubeEventIdRow[];
    className?: string;
}) {
    const aggregatedData = congressData.reduce(
        (acc, row) => {
            acc.total_videos += row.total_videos;
            acc.missing_event_id += row.missing_event_id;
            return acc;
        },
        { total_videos: 0, missing_event_id: 0 }
    );
    const missingFraction = aggregatedData.missing_event_id / aggregatedData.total_videos;
    const chartData = [
        {
            name: "has event id",
            fraction: 1 - missingFraction,
            fill: colors.green[600],
        },
        {
            name: "missing event id",
            fraction: missingFraction,
            fill: colors.red[600],
        },
    ];
    return (
        <Card className="flex flex-col">
            <CardContent className="flex-1 pb-0">
                <ChartContainer
                    config={chartConfig}
                    className="mx-auto aspect-square max-h-[250px]"
                >
                    <PieChart>
                        <Pie
                            data={chartData}
                            dataKey="fraction"
                            nameKey="name"
                            innerRadius={"50%"}
                            strokeWidth={5}
                        >
                            <Label
                                content={({ viewBox }) => {
                                    if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                                        return (
                                            <text
                                                x={viewBox.cx}
                                                y={viewBox.cy}
                                                textAnchor="middle"
                                                dominantBaseline="middle"
                                            >
                                                <tspan
                                                    x={viewBox.cx}
                                                    y={viewBox.cy}
                                                    className="fill-foreground text-2xl font-bold"
                                                >
                                                    {(missingFraction * 100).toFixed(0)}%
                                                </tspan>
                                                <tspan
                                                    x={viewBox.cx}
                                                    y={(viewBox.cy || 0) + 24}
                                                    className="fill-muted-foreground"
                                                >
                                                    missing EventIDs
                                                </tspan>
                                            </text>
                                        );
                                    }
                                }}
                            />
                        </Pie>
                    </PieChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
}

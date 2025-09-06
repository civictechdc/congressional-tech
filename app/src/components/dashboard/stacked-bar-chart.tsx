"use client";
import { cn } from "@/lib/utils";
import { ReactNode } from "react";

import colors from "tailwindcss/colors";

import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts";

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
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";
import { CongressNumber } from "@/types/congress-metadata";

const chartConfig = {
    hasEventId: {
        color: colors.green[600],
        label: "has",
    },
    missingEventId: {
        color: colors.red[600],
        label: "missing",
    },
} satisfies ChartConfig;

type ChartMetadata = {
    title: string | ReactNode;
    subtitle: string | ReactNode;
    footer: string | ReactNode;
};

export function StackedBarChart({
    congressData,
    className = "",
}: {
    congressData: YoutubeEventIdRow[];
    className: string;
}) {
    return (
        <Card className={cn(className, "flex")}>
            <CardContent className="flex-1">
                <ChartContainer config={chartConfig} className="h-full w-full">
                    <BarChart accessibilityLayer data={congressData} barSize={50}>
                        <CartesianGrid vertical={false} />
                        <YAxis type="number" tickCount={5} />
                        <XAxis
                            type="category"
                            dataKey="handle"
                            tickLine={false}
                            tickMargin={10}
                            axisLine={false}
                            tickFormatter={(value) => ""}
                        />
                        <ChartTooltip content={<ChartTooltipContent hideLabel={false} />} />
                        <ChartLegend content={<ChartLegendContent />} verticalAlign="top" />
                        <Bar
                            dataKey={(d) => Math.max(1, d.total_videos - d.missing_event_id)}
                            name="Has EventID"
                            label="Has EventID"
                            stackId="a"
                            fill="var(--color-hasEventId)"
                            radius={[0, 0, 4, 4]}
                        ></Bar>
                        <Bar
                            dataKey="missing_event_id"
                            name="Missing EventID"
                            label="Missing EventID"
                            stackId="a"
                            fill="var(--color-missingEventId)"
                            radius={[4, 4, 0, 0]}
                        ></Bar>
                    </BarChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
}

"use client";

import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts";
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
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";
import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";
import { cn } from "@/lib/utils";
import { ReactNode } from "react";

export const description = "A stacked bar chart with a legend";

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
    data,
    chartMeta = {} as ChartMetadata,
    className = "",
}: {
    data: YoutubeEventIdRow[];
    chartMeta: ChartMetadata;
    className: string;
}) {
    console.log(data);
    return (
        <Card className={cn(className, "flex")} style={{ height: data.length * 30 }}>
            <CardHeader>
                <CardTitle>{chartMeta.title}</CardTitle>
                <CardDescription>{chartMeta.subtitle}</CardDescription>
            </CardHeader>
            <CardContent className="flex-1">
                <ChartContainer config={chartConfig} className="h-full w-full">
                    <BarChart accessibilityLayer data={data} layout="vertical" barSize={50}>
                        <CartesianGrid vertical={false} />
                        <XAxis type="number" />
                        <YAxis
                            type="category"
                            dataKey="handle"
                            tickLine={false}
                            tickMargin={10}
                            axisLine={false}
                            hide
                            //tickFormatter={(value) => value.slice(0, 3)}
                        />
                        <ChartTooltip content={<ChartTooltipContent hideLabel={false} />} />
                        <ChartLegend content={<ChartLegendContent />} verticalAlign="top" />
                        <Bar
                            dataKey={(d) => Math.max(1, d.total_videos - d.missing_event_id)}
                            name="Has EventID"
                            label="Has EventID"
                            stackId="a"
                            fill="var(--color-hasEventId)"
                            radius={[4, 0, 0, 4]}
                        ></Bar>
                        <Bar
                            dataKey="missing_event_id"
                            name="Missing EventID"
                            label="Missing EventID"
                            stackId="a"
                            fill="var(--color-missingEventId)"
                            radius={[0, 4, 4, 0]}
                        >
                            <LabelList
                                dataKey="handle"
                                position="insideRight"
                                offset={8}
                                fill="white"
                                // keep your working workaround; some versions need stringly props
                                clip={"false"}
                            />
                        </Bar>
                    </BarChart>
                </ChartContainer>
            </CardContent>
            <CardFooter className="flex-col items-start gap-2 text-sm">
                {chartMeta.footer}
            </CardFooter>
        </Card>
    );
}

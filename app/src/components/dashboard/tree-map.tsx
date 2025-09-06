import React from "react";
import { Tooltip, Treemap } from "recharts";

type TreeNode = {
    name: string;
    children?: TreeNode[];
    size?: number;
    fill?: string;
};

// Recharts Treemap `content` expects a ReactElement, so we provide a component
// (typing a subset of the props we actually use to avoid `any` where possible)
interface TreemapNodeProps {
    x?: number;
    y?: number;
    width?: number;
    height?: number;
    name?: string;
    value?: number;
    fill?: string;
}

function TreemapNodeWithGap({
    x,
    y,
    width,
    height,
    fill,
    ...rest
}: TreemapNodeProps): React.ReactElement {
    const gap = 0; // px inset on each side
    const x0 = (x ?? 0) + gap;
    const y0 = (y ?? 0) + gap;
    const w = Math.max(0, (width ?? 0) - gap * 2);
    const h = Math.max(0, (height ?? 0) - gap * 2);
    return (
        <g>
            {rest?.depth > 1 && (
                <>
                    <rect
                        x={x0}
                        y={y0}
                        width={w}
                        height={h}
                        fill={fill ?? "#FFF"}
                        stroke={rest?.depth == 1 ? "#000" : "#fff"}
                        strokeWidth={rest?.depth == 1 ? 0 : 2}
                        radius={5}
                    />
                    {w > 40 && h > 12 && rest?.name && (
                        <text
                            x={x0}
                            y={y0 + h / 2}
                            textAnchor="start"
                            dominantBaseline="middle"
                            fontSize={12}
                            fill="#000"
                        >
                            {rest.name}
                        </text>
                    )}
                </>
            )}
        </g>
    );
}

import { YoutubeEventIdRow } from "@/hooks/use-youtube-event-id-report";
import { Card, CardContent } from "../ui/card";
import { ChartContainer, ChartTooltip } from "../ui/chart";
import { cn } from "@/lib/utils";

export function TreeMap({
    congressData,
    className = "",
}: {
    congressData: YoutubeEventIdRow[];
    className?: string;
}) {
    const treemapData: TreeNode[] = congressData.map((row) => {
        const missingFraction = row.missing_event_id / row.total_videos;
        return {
            name: row.handle,
            children: [
                {
                    name: `${row.handle}-missing`,
                    size: row.total_videos * missingFraction,
                    fill: "red",
                },
                {
                    name: `${row.handle}-has`,
                    size: row.total_videos * (1 - missingFraction),
                    fill: "green",
                },
            ],
        };
    });
    return (
        <Card className={cn(className)}>
            <CardContent className="flex-1">
                <ChartContainer config={{}} className="h-full w-full">
                    <Treemap
                        type="flat"
                        nameKey="name"
                        data={treemapData}
                        dataKey="size"
                        content={<TreemapNodeWithGap />}
                    >
                        <Tooltip />
                    </Treemap>
                </ChartContainer>
            </CardContent>
        </Card>
    );
}

import React from "react";
import { Tooltip, Treemap } from "recharts";

import colors from "tailwindcss/colors";

const GREEN = colors.green[600];
const RED = colors.red[600];

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
    depth?: number;
}

function TreemapNodeWithGap({
    x,
    y,
    width,
    height,
    fill,
    depth = 1,
    ...rest
}: TreemapNodeProps): React.ReactElement {
    const gap = 0; // px inset on each side
    const x0 = (x ?? 0) + gap;
    const y0 = (y ?? 0) + gap;
    const w = Math.max(0, (width ?? 0) - gap * 2);
    const h = Math.max(0, (height ?? 0) - gap * 2);
    const fontSizePx = 12;

    return (
        <g>
            {depth > 0 && (
                <>
                    <rect
                        x={x0}
                        y={y0}
                        width={depth > 1 ? w - 2 * (depth == 1 ? 0 : 2) : w}
                        height={depth > 1 ? h - 2 * (depth == 1 ? 0 : 2) : h}
                        fill={fill ?? RED}
                        stroke={depth == 1 ? "black" : "transparent"}
                        strokeWidth={depth == 1 ? 0 : 0}
                    />
                    {w > 40 && h > 12 && rest?.name && (
                        <g>
                            <clipPath id={`clip-${rest.name}`}>
                                <rect x={x0} y={y0} width={w - 4} height={h} />
                            </clipPath>
                            <text
                                x={x0 + 2}
                                y={y0 + fontSizePx / 2 + h / 4}
                                textAnchor="start"
                                dominantBaseline="middle"
                                fontSize={`${fontSizePx}px`}
                                fill="#000"
                                clipPath={`url(#clip-${rest.name})`}
                                style={{
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                    wordBreak: "break-all",
                                }}
                            >
                                {rest.name}
                            </text>
                        </g>
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
    const committeesMap = congressData.reduce<Record<string, YoutubeEventIdRow[]>>((acc, row) => {
        if (!acc[row.committee_name]) {
            acc[row.committee_name] = [];
        }
        acc[row.committee_name].push(row);
        return acc;
    }, {});

    const treemapData: TreeNode[] = Object.entries(committeesMap).map(([committeeName, rows]) => ({
        name: "foo bar",
        fill: "blue",
        size: 5000,
        children: rows.map((row) => {
            const missingFraction = row.missing_event_id / row.total_videos;
            const tooltipContent = {
                committeeName: row.committee_name,
                handle: row.handle,
                totalVideos: row.total_videos,
                missingFraction: (100 * missingFraction).toFixed(2),
            };
            return {
                name: row.handle,
                tooltip: tooltipContent,
                size: row.total_videos,
                children: [
                    {
                        name: null,
                        tooltip: tooltipContent,
                        size: row.total_videos * missingFraction,
                        fill: "transparent",
                    },
                    {
                        name: null,
                        tooltip: tooltipContent,
                        size: row.total_videos * (1 - missingFraction),
                        fill: GREEN,
                    },
                ],
            };
        }),
    }));

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
                        animationDuration={750}
                    >
                        <Tooltip
                            defaultIndex={1}
                            active={true}
                            trigger={"click"}
                            filterNull={false}
                            content={({ active, payload, ...rest }) => {
                                console.log(active, payload?.[0], rest);
                                return (
                                    <div className="rounded border border-gray-200 bg-white p-3 shadow-md">
                                        <div className="font-semibold">{`Committee: ${payload?.[0]?.payload?.tooltip?.committeeName}`}</div>
                                        <div>{`Handle: ${payload?.[0]?.payload?.tooltip?.handle}`}</div>
                                        <div>{`Total Videos: ${payload?.[0]?.payload?.tooltip?.totalVideos}`}</div>
                                        <div>{`Missing Fraction: ${payload?.[0]?.payload?.tooltip?.missingFraction}%`}</div>
                                    </div>
                                );
                            }}
                        />
                    </Treemap>
                </ChartContainer>
            </CardContent>
        </Card>
    );
}

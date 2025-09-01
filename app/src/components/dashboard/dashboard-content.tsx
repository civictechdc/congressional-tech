"use client";
import { LucideArrowRight } from "lucide-react";

import { CongressMetadata, CongressNumber } from "@/types/congress-metadata";
import congressMetadataJson from "@/data/congress_metadata.json";

import useYoutubeEventIdReport from "@/hooks/use-youtube-event-id-report";

import { StackedBarChart } from "./stacked-bar-chart";

const congressMetadata: CongressMetadata = congressMetadataJson;

export function DashboardContent({}) {
    const { data, error, isError, isLoading } = useYoutubeEventIdReport();

    if (isLoading) return null;
    if (isError) throw error;
    if (!data) return null;

    const congressNumbers = Array.from(
        new Set(
            data
                .filter((eventIdRow) => eventIdRow.total_videos > 0)
                .map((eventIdRow) => eventIdRow.congress_number)
        )
    )
        .sort((a, b) => a - b)
        .reverse();
    return (
        <div className="grid w-screen grid-cols-2 gap-4 p-4 md:grid-cols-4">
            {congressNumbers.map((congressNumber) => {
                const startString = `${congressMetadata[congressNumber.toString() as CongressNumber].start}`;
                const endString = `${congressMetadata[congressNumber.toString() as CongressNumber].end}`;
                const subtitle = (
                    <p className="flex flex-row items-center gap-1">
                        {startString} <LucideArrowRight size={16} /> {endString}
                    </p>
                );
                return (
                    <StackedBarChart
                        key={`${congressNumber}-stacked-chart`}
                        chartMeta={{
                            title: `${congressNumber}th Congress`,
                            subtitle,
                            footer: `${congressMetadata?.[congressNumber.toString() as CongressNumber].house} majority`,
                        }}
                        className="col-span-2"
                        data={data.filter(
                            (eventIdRow) => eventIdRow.congress_number === congressNumber
                        )}
                    />
                );
            })}
        </div>
    );
}

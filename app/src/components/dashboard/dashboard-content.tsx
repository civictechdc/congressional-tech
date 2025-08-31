"use client";
import useYoutubeEventIdReport from "@/hooks/use-youtube-event-id-report";
import { StackedBarChart } from "./stacked-bar-chart";
import congressMetadata from "@/data/congress_metadata.json";
import { LucideArrowBigRight, LucideArrowRight } from "lucide-react";

export function DashboardContent({}) {
    const { data, error, isError, isLoading } = useYoutubeEventIdReport();

    if (isError || isLoading || !data) return null;

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
                const startString = `${congressMetadata[congressNumber.toString()].start}`;
                const endString = `${congressMetadata[congressNumber.toString()].end}`;
                const subtitle = (
                    <p className="flex flex-row items-center gap-1">
                        {startString} <LucideArrowRight size={16} /> {endString}
                    </p>
                );
                return (
                    <StackedBarChart
                        chartMeta={{
                            title: `${congressNumber}th Congress`,
                            subtitle,
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

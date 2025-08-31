"use client";
import useYoutubeEventIdReport from "@/hooks/use-youtube-event-id-report";
import { StackedBarChart } from "./stacked-bar-chart";

export function DashboardContent({}) {
    const { data, error, isError, isLoading } = useYoutubeEventIdReport();

    if (isError || isLoading || !data) return null;

    const subsetData = data.filter((eventIdRow) => eventIdRow.congress_number === 119);
    return (
        <div className="grid grid-cols-4 gap-4 p-4">
            <StackedBarChart className="col-span-2" data={subsetData} />
            <StackedBarChart className="col-span-2" data={subsetData} />
        </div>
    );
}

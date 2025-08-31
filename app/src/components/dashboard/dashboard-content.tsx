"use client";
import useYoutubeEventIdReport from "@/hooks/use-youtube-event-id-report";
import { StackedBarChart } from "./stacked-bar-chart";

export function DashboardContent({}) {
    const { data, error, isError, isLoading } = useYoutubeEventIdReport();

    if (isError || isLoading || !data) return null;

    const data119 = data.filter((eventIdRow) => eventIdRow.congress_number === 119);
    const data118 = data.filter((eventIdRow) => eventIdRow.congress_number === 118);
    return (
        <div className="grid w-screen grid-cols-2 gap-4 p-4 md:grid-cols-4">
            <StackedBarChart className="col-span-2" data={data119} />
            <StackedBarChart className="col-span-2" data={data118} />
        </div>
    );
}

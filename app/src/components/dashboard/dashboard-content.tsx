"use client";
import useYoutubeEventIdReport from "@/hooks/use-youtube-event-id-report";

export function DashboardContent({}) {
    const { data, error, isError, isLoading } = useYoutubeEventIdReport();
    console.log(data, isLoading);
    return <div></div>;
}

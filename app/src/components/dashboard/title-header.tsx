import { cn } from "@/lib/utils";
import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";

import { CongressNumber, CongressMetadata } from "@/types/congress-metadata";
import congressMetadataJson from "@/data/congress_metadata.json";
import { ArrowRight } from "lucide-react";

const congressMetadata = congressMetadataJson as CongressMetadata;

export function TitleHeader({
    congressNumber,
    className = "",
}: {
    congressNumber: CongressNumber;
    className?: string;
}) {
    /*
            <CardHeader>
                <CardTitle>{chartMeta.title}</CardTitle>
            </CardHeader>

            <CardFooter className="flex-col items-start gap-2 text-sm">
                {chartMeta.footer}
            </CardFooter>
            */
    const startString = `${congressMetadata[congressNumber.toString() as CongressNumber].start}`;
    const endString = `${congressMetadata[congressNumber.toString() as CongressNumber].end}`;
    return (
        <Card className={cn(className)}>
            <CardHeader>
                <CardTitle>{`${congressNumber}th Congress`}</CardTitle>
                <CardDescription>
                    <p className="flex flex-row items-center gap-1">
                        {startString} <ArrowRight size={16} /> {endString}
                    </p>
                </CardDescription>
                {congressMetadata?.[congressNumber.toString() as CongressNumber].house} majority
            </CardHeader>
        </Card>
    );
}

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
import { Button } from "../ui/button";

const congressMetadata = congressMetadataJson as CongressMetadata;

export function TitleHeader({
    congressNumber,
    setCongressNumber,
    className = "",
}: {
    congressNumber: CongressNumber;
    setCongressNumber: React.Dispatch<React.SetStateAction<CongressNumber>>;
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

    const minCongress = 105;
    const maxCongress = 119;
    const congressNum = Number(congressNumber);

    return (
        <Card className={cn("", className)}>
            <CardHeader>
                <CardTitle>
                    <div className="mb-4 flex items-center justify-center space-x-4">
                        <Button
                            onClick={() => {
                                if (congressNum > minCongress) {
                                    window.history.pushState(
                                        {},
                                        "",
                                        `?congress=${congressNum - 1}`
                                    );
                                    setCongressNumber(
                                        (congressNum - 1).toString() as CongressNumber
                                    );
                                }
                            }}
                            disabled={congressNum <= minCongress}
                        >
                            Previous
                        </Button>
                        <span className="text-lg font-semibold">{congressNumber}th Congress</span>
                        <Button
                            onClick={() => {
                                if (congressNum < maxCongress) {
                                    window.history.pushState(
                                        {},
                                        "",
                                        `?congress=${congressNum + 1}`
                                    );
                                    setCongressNumber(
                                        (congressNum + 1).toString() as CongressNumber
                                    );
                                }
                            }}
                            disabled={congressNum >= maxCongress}
                        >
                            Next
                        </Button>
                    </div>
                </CardTitle>
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

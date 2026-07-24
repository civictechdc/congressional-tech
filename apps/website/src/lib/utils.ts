import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names, de-duplicating conflicting Tailwind utilities.
 * Standard shadcn/ui helper.
 */
export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

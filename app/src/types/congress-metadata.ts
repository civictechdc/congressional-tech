// congress-metadata.ts
export type CongressNumber =
    | "106"
    | "107"
    | "108"
    | "109"
    | "110"
    | "111"
    | "112"
    | "113"
    | "114"
    | "115"
    | "116"
    | "117"
    | "118"
    | "119";

export interface CongressSession {
    name: string;
    start: string; // ISO date
    end: string; // ISO date or "present"
    // Occasionally a session row overrides chamber control (e.g., 107th)
    senate?: string;
    house?: string;
}

export interface CongressTerm {
    start: string; // ISO date
    end: string; // ISO date
    senate: string; // e.g., "Republican", "Democratic", or mixed text like "Democratic / Republican / Democratic"
    house: string;
    sessions: CongressSession[];
}

// Finite-keyed map
export type CongressMetadata = Record<CongressNumber, CongressTerm>;

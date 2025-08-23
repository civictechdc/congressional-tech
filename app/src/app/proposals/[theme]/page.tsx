import { type FC } from "react";

import projectThemes from "@/data/project-themes.json";

export async function generateStaticParams() {
    return projectThemes.map((theme) => ({
        theme: theme.id,
    }));
}

interface ThemePageProps {
    params: {
        theme: string;
    };
}

const ThemePage: FC<ThemePageProps> = ({ params }) => {
    return (
        <main className="flex min-h-screen items-center justify-center bg-gray-50">
            <h1 className="text-2xl font-bold text-gray-900">Theme: {params.theme}</h1>
        </main>
    );
};

export default ThemePage;

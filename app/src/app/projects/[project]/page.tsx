import { type FC } from "react";

import activeProjects from "@/data/active-projects.json";

export async function generateStaticParams() {
    return activeProjects.map((project) => ({
        project: project.id,
    }));
}

interface ProjectPageProps {
    params: {
        project: string;
    };
}

const ProjectPage: FC<ProjectPageProps> = ({ params }) => {
    return (
        <main className="flex min-h-screen items-center justify-center bg-gray-50">
            <h1 className="text-2xl font-bold text-gray-900">Project: {params.project}</h1>
        </main>
    );
};

export default ProjectPage;

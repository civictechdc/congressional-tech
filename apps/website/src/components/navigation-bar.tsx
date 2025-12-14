"use client";

import * as React from "react";
import Link from "next/link";
import projectThemes from "@/data/project-themes.json";
import activeProjects from "@/data/active-projects.json";

import {
    NavigationMenu,
    NavigationMenuContent,
    NavigationMenuItem,
    NavigationMenuLink,
    NavigationMenuList,
    NavigationMenuTrigger,
    navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu";

export function NavBar() {
    return (
        <NavigationMenu viewport={false} className="">
            <NavigationMenuList>
                <NavigationMenuItem>
                    <NavigationMenuTrigger>Home</NavigationMenuTrigger>
                    <NavigationMenuContent>
                        <ul className="grid gap-2 md:w-[400px] lg:w-[500px] lg:grid-cols-[.75fr_1fr]">
                            <li className="row-span-3">
                                <NavigationMenuLink asChild>
                                    <a
                                        className="from-muted/50 to-muted flex h-full w-full flex-col justify-end rounded-md bg-linear-to-b p-6 no-underline outline-hidden select-none focus:shadow-md"
                                        href="https://civictechdc.org"
                                        target="_blank"
                                    >
                                        <div className="mt-4 mb-2 text-lg font-medium">
                                            Civic Tech DC homepage
                                        </div>
                                        <p className="text-muted-foreground text-sm leading-tight">
                                            civictechdc.org
                                        </p>
                                    </a>
                                </NavigationMenuLink>
                            </li>
                            <li>
                                <NavigationMenuLink asChild>
                                    <a
                                        href="https://www.civictechdc.org/projects/congressional-modernization.html"
                                        target="_blank"
                                    >
                                        <div className="text-sm leading-none font-medium">
                                            Project Page
                                        </div>
                                        <p className="text-muted-foreground line-clamp-2 text-sm leading-snug">
                                            The official Civic Tech DC page for this project
                                        </p>
                                    </a>
                                </NavigationMenuLink>
                            </li>
                            <li>
                                <NavigationMenuLink asChild>
                                    <a
                                        href="https://www.github.com/civictechdc/congressional-tech"
                                        target="_blank"
                                    >
                                        <div className="text-sm leading-none font-medium">
                                            Github Repo
                                        </div>
                                        <p className="text-muted-foreground line-clamp-2 text-sm leading-snug">
                                            Github repository for this project
                                        </p>
                                    </a>
                                </NavigationMenuLink>
                            </li>
                        </ul>
                    </NavigationMenuContent>
                </NavigationMenuItem>
                <NavigationMenuItem>
                    <NavigationMenuTrigger>Active Projects</NavigationMenuTrigger>
                    <NavigationMenuContent>
                        <ul className="grid w-[400px] gap-2 md:w-[500px] md:grid-cols-2 lg:w-[600px]">
                            {activeProjects.map((project) => (
                                <ListItem
                                    key={project.title}
                                    title={`${project.title}`}
                                    href={`/projects/${project.id}`}
                                >
                                    {project.description}
                                </ListItem>
                            ))}
                        </ul>
                    </NavigationMenuContent>
                </NavigationMenuItem>
                <NavigationMenuItem>
                    <NavigationMenuTrigger>
                        <Link href="proposals">Project Proposals</Link>
                    </NavigationMenuTrigger>
                    <NavigationMenuContent>
                        <ul className="grid w-[400px] gap-2 md:w-[500px] md:grid-cols-2 lg:w-[600px]">
                            {projectThemes.map((theme) => (
                                <ListItem
                                    key={theme.title}
                                    title={`${theme.title}`}
                                    href={`/proposals/${theme.id}`}
                                >
                                    {theme.focus}
                                </ListItem>
                            ))}
                        </ul>
                    </NavigationMenuContent>
                </NavigationMenuItem>
                <NavigationMenuItem>
                    <NavigationMenuLink asChild className={navigationMenuTriggerStyle()}>
                        <Link href="/dashboard">Dashboard</Link>
                    </NavigationMenuLink>
                </NavigationMenuItem>
            </NavigationMenuList>
        </NavigationMenu>
    );
}

function ListItem({
    title,
    children,
    href,
    ...props
}: React.ComponentPropsWithoutRef<"li"> & { href: string }) {
    return (
        <li {...props}>
            <NavigationMenuLink asChild>
                <Link href={href}>
                    <div className="text-sm leading-none font-medium">{title}</div>
                    <p className="text-muted-foreground line-clamp-2 text-sm leading-snug">
                        {children}
                    </p>
                </Link>
            </NavigationMenuLink>
        </li>
    );
}

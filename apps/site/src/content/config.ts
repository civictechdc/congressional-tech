import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

/** Keep file names (e.g. "I.2") verbatim as entry ids — no slugification. */
const generateId = ({ entry }: { entry: string }) => entry.replace(/\.md$/, '');

const themeId = z.enum(['I', 'II', 'III', 'IV', 'V']);

const themes = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/themes', generateId }),
  schema: z.object({
    id: themeId,
    title: z.string(),
    tag: z.string(),
    order: z.number().int(),
    focus: z.string().nullable(),
  }),
});

const proposals = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/proposals', generateId }),
  schema: z.object({
    id: z.string(),
    title: z.string(),
    theme: themeId,
    status: z.enum(['idea', 'in-progress', 'built']),
    effort: z.string().optional(),
    repo: z.string().url().optional(),
  }),
});

const projects = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/projects', generateId }),
  schema: z.object({
    id: z.string(),
    title: z.string(),
    theme: themeId,
    status: z.literal('built'),
    description: z.string(),
    repo: z.string().url(),
  }),
});

/**
 * Sub-projects: Congressional Tech tools in their own repositories instead of
 * this monorepo. Some are forks kept in sync with an upstream (e.g. DeltaTrack,
 * BillTrax from AgoraDMV); others are built here. First-class alongside proposals and
 * projects — this collection is the single source of truth for their data.
 */
const subprojects = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/subprojects', generateId }),
  schema: z.object({
    id: z.string(),
    title: z.string(),
    tagline: z.string(),
    repo: z.string().url(),
    upstream: z.string().url().optional(),
    liveUrl: z.string().url().optional(),
    liveLabel: z.string().optional(),
    status: z.enum(['live', 'soft-launch', 'in-development']),
    /** id of the proposal this sub-project advances (e.g. "I.4"). */
    proposal: z.string(),
    order: z.number().int(),
  }),
});

export const collections = { themes, proposals, projects, subprojects };

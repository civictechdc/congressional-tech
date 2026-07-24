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
    status: z.enum(['idea', 'active', 'built']),
    effort: z.string().optional(),
    repo: z.string().url().optional(),
    related: z
      .array(
        z.object({
          label: z.string(),
          href: z.string().url(),
          note: z.string(),
        }),
      )
      .optional(),
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

export const collections = { themes, proposals, projects };

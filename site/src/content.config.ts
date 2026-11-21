import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const transcripts = defineCollection({
  loader: glob({
    base: "./transcripts",
    pattern: "*.md",
    generateId: ({ entry }) => entry.replace(/\.md$/, ""),
  }),
  schema: z.object({
    title: z.string(),
    date: z.coerce.date(),
    categories: z.union([z.string(), z.array(z.string())]),
    slug: z.string().optional(),
    description: z.string().optional(),
  }),
});

export const collections = { transcripts };

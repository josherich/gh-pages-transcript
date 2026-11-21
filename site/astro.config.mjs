import { unified } from "@astrojs/markdown-remark";
import { defineConfig } from "astro/config";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { remarkTranscriptNavigation } from "./src/lib/transcript-navigation.mjs";

const site = new URL(process.env.PAGES_ORIGIN || "https://podcast.josherich.me");
site.protocol = "https:";

export default defineConfig({
  site: site.href,
  base: process.env.PAGES_BASE_PATH || "/",
  trailingSlash: "never",
  build: { format: "file" },
  markdown: {
    processor: unified({
      remarkPlugins: [remarkTranscriptNavigation],
      rehypePlugins: [
        rehypeRaw,
        [rehypeSanitize, {
          ...defaultSchema,
          tagNames: [...defaultSchema.tagNames, "iframe"],
          attributes: {
            ...defaultSchema.attributes,
            iframe: [
              ["src", /^https:\/\/www\.listennotes\.com\/.*\/embed\/$/],
              "title", "width", "height", "loading",
            ],
          },
          strip: ["script", "style"],
        }],
      ],
    }),
  },
});

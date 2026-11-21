import { getCollection } from "astro:content";

const dateFormat = new Intl.DateTimeFormat("en", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function slugify(value: string) {
  return value.toLowerCase().replace(/[^\p{L}\p{N}\p{M}]+/gu, "-").replace(/^-|-$/g, "");
}

export function sitePath(path = "") {
  return [import.meta.env.BASE_URL.replace(/\/$/, ""), path].join("/");
}

export function displayDate(date: Date) {
  return dateFormat.format(date);
}

export async function getTranscripts() {
  const entries = await getCollection("transcripts");
  const paths = new Set<string>();
  return entries
    .map((entry) => {
      const { categories, slug } = entry.data;
      const [section, ...shows] = Array.isArray(categories) ? categories : categories.split(/\s+/);
      const parts = [section, ...shows, slug ?? entry.id.slice(11)].map(slugify);
      if (parts.some((part) => !part)) throw new Error("Invalid transcript path for " + entry.id);
      const path = parts.join("/");
      if (paths.has(path)) throw new Error("Two transcripts map to /" + path);
      paths.add(path);
      return { entry, path, show: shows.join(" ") };
    })
    .sort((a, b) => b.entry.data.date.getTime() - a.entry.data.date.getTime()
      || a.entry.id.localeCompare(b.entry.id));
}

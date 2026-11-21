// Archived posts store their navigation as JSON assignments inside a script.
export function remarkTranscriptNavigation() {
  return (tree, file) => {
    const frontmatter = file.data.astro.frontmatter;

    function extract(node) {
      if (node.type === "html") {
        node.value = node.value.replace(
          /<script\b[^>]*>\s*window\.tocIndex\s*=\s*([\s\S]*?)<\/script>/gi,
          (_, assignments) => {
            const [toc, faq] = assignments.split(/;\s*window\.faq\s*=\s*/);
            frontmatter.toc = parseJson(toc)?.index;
            frontmatter.faq = parseJson(faq)?.qas;
            return "";
          },
        );
      }
      node.children?.forEach(extract);
    }

    extract(tree);
  };
}

function parseJson(value) {
  if (!value) return null;
  try {
    return JSON.parse(value.trim().replace(/;$/, ""));
  } catch {
    // Some older generated posts contain incomplete or malformed navigation.
    return null;
  }
}

import type { BundledLanguage } from "shiki";

const BY_EXT: Record<string, BundledLanguage> = {
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  json: "json",
  css: "css",
  html: "html",
  md: "markdown",
  py: "python",
  sh: "bash",
  yml: "yaml",
  yaml: "yaml",
};

export function langForPath(path: string): BundledLanguage {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return BY_EXT[ext] ?? ("text" as BundledLanguage);
}

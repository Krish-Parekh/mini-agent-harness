"use client";

import { useEffect, useReducer, type CSSProperties } from "react";
import {
  bundledLanguages,
  createHighlighter,
  type BundledLanguage,
  type HighlighterGeneric,
  type BundledTheme,
  type ThemedToken,
} from "shiki";

type Highlighter = HighlighterGeneric<BundledLanguage, BundledTheme>;

const MAX_CHARS = 200_000;
const MAX_CACHE = 120;

let highlighter: Promise<Highlighter> | null = null;
const languages = new Map<string, Promise<string>>();
const tokens = new Map<string, ThemedToken[][]>();
const pending = new Map<string, Promise<void>>();

function getHighlighter() {
  highlighter ??= createHighlighter({
    langs: [],
    themes: ["github-light", "github-dark"],
  });
  return highlighter;
}

function loadLanguage(hl: Highlighter, lang: string): Promise<string> {
  if (!(lang in bundledLanguages)) return Promise.resolve("text");
  let loaded = languages.get(lang);
  if (!loaded) {
    loaded = hl
      .loadLanguage(lang as BundledLanguage)
      .then(() => lang)
      .catch(() => "text");
    languages.set(lang, loaded);
  }
  return loaded;
}

function cacheKey(code: string, lang: string) {
  return `${lang}\u0000${code}`;
}

export function cachedTokens(code: string, lang: string) {
  return tokens.get(cacheKey(code, lang)) ?? null;
}

function highlight(code: string, lang: string): Promise<void> {
  const key = cacheKey(code, lang);
  let job = pending.get(key);
  if (job) return job;
  job = getHighlighter()
    .then(async (hl) => {
      const resolved = await loadLanguage(hl, lang);
      const result = hl.codeToTokens(code, {
        lang: resolved as BundledLanguage,
        themes: { light: "github-light", dark: "github-dark" },
        tokenizeMaxLineLength: 2000,
      });
      if (tokens.size >= MAX_CACHE) {
        const oldest = tokens.keys().next().value;
        if (oldest !== undefined) tokens.delete(oldest);
      }
      tokens.set(key, result.tokens);
    })
    .catch(() => {})
    .finally(() => {
      pending.delete(key);
    });
  pending.set(key, job);
  return job;
}

export function useHighlightedTokens(
  code: string,
  lang: BundledLanguage,
): ThemedToken[][] | null {
  const [, refresh] = useReducer((n: number) => n + 1, 0);
  const skip = code.length > MAX_CHARS || code.length === 0;
  const result = skip ? null : cachedTokens(code, lang);

  useEffect(() => {
    if (skip || result) return;
    let live = true;
    highlight(code, lang).then(() => {
      if (live) refresh();
    });
    return () => {
      live = false;
    };
  }, [code, lang, skip, result]);

  return result;
}

export function CodeToken({ token }: { token: ThemedToken }) {
  return (
    <span
      className="dark:text-(--shiki-dark)!"
      style={{ color: token.color, ...token.htmlStyle } as CSSProperties}
    >
      {token.content}
    </span>
  );
}

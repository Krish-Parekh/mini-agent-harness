"use client";

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import type { BundledLanguage, ThemedToken } from "shiki";

import { CodeToken, useHighlightedTokens } from "@/components/bui/highlight";
import { cn } from "@/lib/utils";

export function gutterWidth(maxLine: number) {
  return Math.max(20, String(maxLine).length * 7 + 10);
}

export function FileCodeIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("shrink-0 text-ink-3", className)}
    >
      <path d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5" />
    </svg>
  );
}

export function CopyButton({
  text,
  className,
  label = "Copy",
}: {
  text: string;
  className?: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = useCallback(() => {
    if (!navigator.clipboard?.writeText) return;
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  }, [text]);

  return (
    <button
      type="button"
      aria-label={copied ? "Copied" : "Copy code"}
      onClick={copy}
      className={cn(
        "flex h-6 items-center gap-1 rounded-chip px-1.5 text-[12px] font-medium transition-colors duration-100 hover:bg-hover",
        copied ? "text-green" : "text-ink-3 hover:text-ink",
        className,
      )}
    >
      {copied ? (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="12" height="12" rx="2.5" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
      {copied ? "Copied" : label}
    </button>
  );
}

export function LineContent({
  text,
  tokens,
}: {
  text: string;
  tokens: ThemedToken[] | undefined;
}) {
  if (!tokens) return text || " ";
  if (tokens.length === 0) return " ";
  return tokens.map((token, i) => <CodeToken key={i} token={token} />);
}

const CodeLines = memo(function CodeLines({
  lines,
  tokens,
  showLineNumbers,
}: {
  lines: string[];
  tokens: ThemedToken[][] | null;
  showLineNumbers: boolean;
}) {
  if (!showLineNumbers) {
    return (
      <code className="block px-3 break-words whitespace-pre-wrap">
        {lines.map((line, i) => (
          <span key={i} className="block">
            <LineContent text={line} tokens={tokens?.[i]} />
          </span>
        ))}
      </code>
    );
  }
  return (
    <div
      className="relative"
      style={{ "--gutter": `${gutterWidth(lines.length)}px` } as CSSProperties}
    >
      <span className="pointer-events-none absolute inset-y-0 left-(--gutter) w-px bg-line" />
      {lines.map((line, i) => (
        <div key={i} className="grid grid-cols-[var(--gutter)_minmax(0,1fr)] items-start">
          <span className="select-none pr-1.5 text-right text-[11px] text-ink-3 tabular-nums">
            {i + 1}
          </span>
          <code className="pr-3 pl-2 break-words whitespace-pre-wrap">
            <LineContent text={line} tokens={tokens?.[i]} />
          </code>
        </div>
      ))}
    </div>
  );
});

export type CodeBlockProps = {
  code: string;
  language: BundledLanguage;
  filename?: string;
  showLineNumbers?: boolean;
  flush?: boolean;
  className?: string;
};

export function CodeBlock({
  code,
  language,
  filename,
  showLineNumbers = true,
  flush = false,
  className,
}: CodeBlockProps) {
  const lines = useMemo(() => code.split("\n"), [code]);
  const tokens = useHighlightedTokens(code, language);

  return (
    <div
      data-language={language}
      className={cn(
        "group/code relative w-full bg-surface",
        flush ? "" : "overflow-clip rounded-card shadow-card",
        className,
      )}
      style={{ containIntrinsicSize: "auto 200px", contentVisibility: "auto" }}
    >
      {filename !== undefined ? (
        <div className="sticky top-0 z-10 flex h-10 items-center gap-2 border-b border-line bg-surface px-3 text-[12.5px]">
          <span className="inline-flex min-w-0 items-center gap-[7px]">
            <FileCodeIcon />
            <span className="truncate font-mono leading-none text-ink">{filename}</span>
          </span>
          <CopyButton text={code} className="-mr-1 ml-auto" />
        </div>
      ) : (
        <CopyButton
          text={code}
          className="absolute top-1.5 right-1.5 z-10 bg-surface opacity-0 shadow-btn transition-opacity group-hover/code:opacity-100 focus-visible:opacity-100"
        />
      )}
      <div className="py-3 font-mono text-[12.5px] leading-[1.65] text-ink-2">
        <CodeLines lines={lines} tokens={tokens} showLineNumbers={showLineNumbers} />
      </div>
    </div>
  );
}

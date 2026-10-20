"use client";

import { useEffect, useRef, useState, type HTMLAttributes } from "react";

import { Markdown } from "@/components/bui/markdown";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

export type Source = { url: string; host: string; title?: string };

export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function uniqueSources(
  results: { url: string; title?: string }[],
): Source[] {
  const seen = new Set<string>();
  const out: Source[] = [];
  for (const result of results) {
    if (!result.url) continue;
    const host = sourceHost(result.url);
    if (seen.has(host)) continue;
    seen.add(host);
    out.push({ url: result.url, host, title: result.title?.trim() || undefined });
  }
  return out;
}

export function Favicon({ host, className }: { host: string; className?: string }) {
  return (
    <Avatar className={cn("size-4 rounded-[4px] after:border-0", className)}>
      <AvatarImage
        src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`}
        alt=""
        className="rounded-[inherit]"
      />
      <AvatarFallback className="rounded-[inherit] bg-inset text-[9px] font-medium text-ink-2">
        {host[0]?.toUpperCase() ?? "?"}
      </AvatarFallback>
    </Avatar>
  );
}

export function SourceList({ sources }: { sources: Source[] }) {
  return (
    <div className="flex flex-col rounded-card bg-inset p-1 shadow-hairline">
      {sources.map((source) => (
        <a
          key={source.url}
          href={source.url}
          target="_blank"
          rel="noreferrer"
          className="flex min-w-0 items-center gap-2 rounded-chip px-1.5 py-1 text-[12px] text-ink-2 transition-colors duration-150 hover:bg-hover hover:text-ink"
        >
          <Favicon host={source.host} />
          <span className="min-w-0 truncate">{source.title ?? source.host}</span>
          <span className="ml-auto shrink-0 font-mono text-[10.5px] text-ink-3">
            {source.host}
          </span>
        </a>
      ))}
    </div>
  );
}

export function SourcesToggle({
  sources,
  open,
  onToggle,
}: {
  sources: Source[];
  open: boolean;
  onToggle: () => void;
}) {
  const shown = sources.slice(0, 4);
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      className="flex items-center gap-1.5 rounded-chip px-1 py-0.5 text-left transition-colors duration-150 hover:bg-hover"
    >
      <span className="flex -space-x-1">
        {shown.map((source) => (
          <Favicon
            key={source.host}
            host={source.host}
            className="size-3.5 rounded-full bg-surface shadow-[0_0_0_1.5px_var(--canvas)]"
          />
        ))}
      </span>
      <span className="text-[12px] text-ink-2">
        {sources.length} {sources.length === 1 ? "source" : "sources"}
      </span>
    </button>
  );
}

export function UserBubble({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex justify-end pl-14", className)} {...props}>
      <div className="min-w-0 max-w-full whitespace-pre-wrap break-words rounded-xl bg-field px-3.5 py-2 text-[14px] leading-[1.5] text-ink">
        {children}
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const copy = () => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <button
      type="button"
      aria-label={copied ? "Copied" : "Copy message"}
      onClick={copy}
      className="flex size-6 items-center justify-center rounded-chip text-ink-3 transition-colors duration-100 hover:bg-hover-2 hover:text-ink-2"
    >
      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        {copied ? (
          <path d="M20 6L9 17l-5-5" />
        ) : (
          <>
            <rect x="9" y="9" width="12" height="12" rx="2.5" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </>
        )}
      </svg>
    </button>
  );
}

export function AssistantMessage({
  text,
  sources,
  className,
}: {
  text: string;
  sources?: Source[];
  className?: string;
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const hasSources = !!sources && sources.length > 0;
  return (
    <div
      className={cn("group/reply flex w-full min-w-0 flex-col", className)}
      style={{ animation: "fade-up 350ms var(--ease-out-strong) both" }}
    >
      <div className="min-w-0 text-[14px] leading-relaxed text-ink">
        <Markdown>{text}</Markdown>
      </div>
      <div className="mt-2 flex items-center gap-0.5">
        <span className="flex opacity-0 transition-opacity duration-150 group-hover/reply:opacity-100 focus-within:opacity-100">
          <CopyButton text={text} />
        </span>
        {hasSources && (
          <span className="ml-1.5">
            <SourcesToggle
              sources={sources}
              open={sourcesOpen}
              onToggle={() => setSourcesOpen((open) => !open)}
            />
          </span>
        )}
      </div>
      {hasSources && sourcesOpen && (
        <div
          className="mt-1.5 max-w-md"
          style={{ animation: "fade-up 250ms var(--ease-out-strong) both" }}
        >
          <SourceList sources={sources} />
        </div>
      )}
    </div>
  );
}

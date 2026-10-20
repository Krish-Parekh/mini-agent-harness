"use client";

import { memo, useMemo, type CSSProperties } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { diffLines } from "diff";
import parseDiff from "parse-diff";
import type { ThemedToken } from "shiki";

import { cn } from "@/lib/utils";
import { langForPath } from "@/lib/lang";
import { useHighlightedTokens } from "@/components/bui/highlight";
import { FileCodeIcon, gutterWidth, LineContent } from "@/components/bui/code-block";

type DiffLineType = "add" | "del" | "normal";

interface ParsedLine {
  type: DiffLineType;
  content: string;
  oldLineNumber?: number;
  newLineNumber?: number;
}

interface ParsedFile {
  oldName?: string | undefined;
  newName?: string | undefined;
  lines: ParsedLine[];
  additions: number;
  deletions: number;
}

function parsePatch(patch: string): ParsedFile[] {
  return parseDiff(patch).map((file) => {
    const lines: ParsedLine[] = [];
    let additions = 0;
    let deletions = 0;
    for (const chunk of file.chunks) {
      let oldLine = chunk.oldStart;
      let newLine = chunk.newStart;
      for (const change of chunk.changes) {
        const content = change.content.slice(1);
        if (change.type === "add") {
          additions++;
          lines.push({ type: "add", content, newLineNumber: newLine++ });
        } else if (change.type === "del") {
          deletions++;
          lines.push({ type: "del", content, oldLineNumber: oldLine++ });
        } else {
          lines.push({
            type: "normal",
            content,
            oldLineNumber: oldLine++,
            newLineNumber: newLine++,
          });
        }
      }
    }
    return { oldName: file.from, newName: file.to, lines, additions, deletions };
  });
}

function computeDiff(
  oldContent: string,
  newContent: string,
): { lines: ParsedLine[]; additions: number; deletions: number } {
  const lines: ParsedLine[] = [];
  let oldLine = 1;
  let newLine = 1;
  let additions = 0;
  let deletions = 0;
  for (const change of diffLines(oldContent, newContent)) {
    for (const content of change.value.replace(/\n$/, "").split("\n")) {
      if (change.added) {
        additions++;
        lines.push({ type: "add", content, newLineNumber: newLine++ });
      } else if (change.removed) {
        deletions++;
        lines.push({ type: "del", content, oldLineNumber: oldLine++ });
      } else {
        lines.push({
          type: "normal",
          content,
          oldLineNumber: oldLine++,
          newLineNumber: newLine++,
        });
      }
    }
  }
  return { lines, additions, deletions };
}

function pairForSplit(lines: ParsedLine[]): [number | null, number | null][] {
  const pairs: [number | null, number | null][] = [];
  let i = 0;
  while (i < lines.length) {
    const type = lines[i]!.type;
    if (type === "normal") {
      pairs.push([i, i]);
      i++;
    } else if (type === "del") {
      const dels: number[] = [];
      while (i < lines.length && lines[i]!.type === "del") dels.push(i++);
      const adds: number[] = [];
      while (i < lines.length && lines[i]!.type === "add") adds.push(i++);
      for (let j = 0; j < Math.max(dels.length, adds.length); j++) {
        pairs.push([dels[j] ?? null, adds[j] ?? null]);
      }
    } else {
      pairs.push([null, i]);
      i++;
    }
  }
  return pairs;
}

const diffViewerVariants = cva("aui-diff-viewer overflow-clip font-mono", {
  variants: {
    variant: {
      default: "rounded-card border border-line bg-surface",
      ghost: "bg-transparent",
      muted: "rounded-card bg-inset shadow-hairline",
    },
    size: {
      sm: "text-[11.5px]",
      default: "text-[12.5px]",
      lg: "text-[13.5px]",
    },
  },
  defaultVariants: { variant: "default", size: "default" },
});

const HATCH =
  "repeating-linear-gradient(45deg, var(--red) 0, var(--red) 1.5px, transparent 1.5px, transparent 3px)";

const ROW_TINT: Record<DiffLineType, string> = {
  add: "bg-green-tint",
  del: "bg-red-tint",
  normal: "",
};

const SIGN_TONE: Record<DiffLineType, string> = {
  add: "text-green",
  del: "text-red",
  normal: "text-ink-3",
};

const SIGN: Record<DiffLineType, string> = { add: "+", del: "−", normal: " " };

function DiffCell({
  line,
  number,
  tokens,
  showLineNumbers,
  className,
}: {
  line: ParsedLine | null;
  number: number | undefined;
  tokens: ThemedToken[] | undefined;
  showLineNumbers: boolean;
  className?: string;
}) {
  const type = line?.type ?? "normal";
  return (
    <div
      data-type={line?.type ?? "empty"}
      className={cn(
        "relative grid min-w-0 items-start",
        showLineNumbers
          ? "grid-cols-[var(--gutter)_14px_minmax(0,1fr)]"
          : "grid-cols-[14px_minmax(0,1fr)]",
        line ? ROW_TINT[type] : "bg-inset",
        className,
      )}
    >
      {line && type !== "normal" && (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-[3px]"
          style={{ background: type === "add" ? "var(--green)" : HATCH }}
        />
      )}
      {showLineNumbers && (
        <span className={cn("select-none pr-1.5 text-right text-[0.88em] tabular-nums", SIGN_TONE[type])}>
          {number ?? ""}
        </span>
      )}
      <span className={cn("select-none text-center", SIGN_TONE[type])}>
        {line ? SIGN[type] : ""}
      </span>
      <code className="pr-3 pl-1 break-words whitespace-pre-wrap">
        {line ? <LineContent text={line.content} tokens={tokens} /> : " "}
      </code>
    </div>
  );
}

const DiffFileLines = memo(function DiffFileLines({
  file,
  viewMode,
  showLineNumbers,
}: {
  file: ParsedFile;
  viewMode: "split" | "unified";
  showLineNumbers: boolean;
}) {
  const language = useMemo(
    () => langForPath(file.newName ?? file.oldName ?? ""),
    [file.newName, file.oldName],
  );
  const code = useMemo(() => file.lines.map((l) => l.content).join("\n"), [file.lines]);
  const tokens = useHighlightedTokens(code, language);
  const gutter = useMemo(() => {
    let max = 0;
    for (const l of file.lines) {
      max = Math.max(max, l.oldLineNumber ?? 0, l.newLineNumber ?? 0);
    }
    return gutterWidth(max);
  }, [file.lines]);
  const pairs = useMemo(
    () => (viewMode === "split" ? pairForSplit(file.lines) : null),
    [viewMode, file.lines],
  );

  return (
    <div
      data-slot="diff-viewer-content"
      className="relative overflow-x-auto py-1.5 leading-[1.65] text-ink-2"
      style={{ "--gutter": `${gutter}px` } as CSSProperties}
    >
      {pairs
        ? pairs.map(([l, r], i) => {
            const left = l === null ? null : file.lines[l]!;
            const right = r === null ? null : file.lines[r]!;
            return (
              <div key={i} data-slot="diff-viewer-split-line" className="grid grid-cols-2">
                <DiffCell
                  line={left}
                  number={left?.oldLineNumber}
                  tokens={l === null ? undefined : tokens?.[l]}
                  showLineNumbers={showLineNumbers}
                  className="border-r border-line"
                />
                <DiffCell
                  line={right}
                  number={right?.newLineNumber}
                  tokens={r === null ? undefined : tokens?.[r]}
                  showLineNumbers={showLineNumbers}
                />
              </div>
            );
          })
        : file.lines.map((line, i) => (
            <DiffCell
              key={i}
              line={line}
              number={line.type === "del" ? line.oldLineNumber : line.newLineNumber}
              tokens={tokens?.[i]}
              showLineNumbers={showLineNumbers}
            />
          ))}
    </div>
  );
});

function DiffViewerHeader({
  oldName,
  newName,
  additions,
  deletions,
  showIcon,
  showStats,
}: {
  oldName?: string | undefined;
  newName?: string | undefined;
  additions: number;
  deletions: number;
  showIcon: boolean;
  showStats: boolean;
}) {
  if (!oldName && !newName) return null;
  const renamed = oldName && newName && oldName !== newName && oldName !== "/dev/null" && newName !== "/dev/null";
  const displayName = newName && newName !== "/dev/null" ? newName : oldName;

  return (
    <div
      data-slot="diff-viewer-header"
      className="sticky top-0 z-10 flex h-10 items-center gap-2 border-b border-line bg-surface px-3 font-sans text-[12.5px]"
    >
      <span className="inline-flex min-w-0 items-center gap-[7px]">
        {showIcon && <FileCodeIcon />}
        <span className="truncate font-mono leading-none text-ink">
          {renamed ? (
            <>
              <span className="text-red">{oldName}</span>
              <span className="text-ink-3"> → </span>
              <span className="text-green">{newName}</span>
            </>
          ) : (
            displayName
          )}
        </span>
      </span>
      {showStats && (additions > 0 || deletions > 0) && (
        <span className="ml-auto inline-flex shrink-0 items-center gap-2 font-mono text-[12px] leading-none tabular-nums">
          <span className="text-green">+{additions}</span>
          <span className="text-red">−{deletions}</span>
        </span>
      )}
    </div>
  );
}

export type DiffViewerProps = VariantProps<typeof diffViewerVariants> & {
    code?: string;
    patch?: string;
    oldFile?: { content: string; name?: string };
    newFile?: { content: string; name?: string };
    viewMode?: "split" | "unified";
    showLineNumbers?: boolean;
    showIcon?: boolean;
    showStats?: boolean;
    className?: string;
  };

function DiffViewer({
  code,
  patch,
  oldFile,
  newFile,
  viewMode = "unified",
  showLineNumbers = true,
  showIcon = true,
  showStats = true,
  variant,
  size,
  className,
}: DiffViewerProps) {
  const diffPatch = patch ?? code;
  const hasFiles = Boolean(oldFile && newFile);
  const oldContent = oldFile?.content ?? "";
  const newContent = newFile?.content ?? "";
  const oldName = oldFile?.name;
  const newName = newFile?.name;

  const parsedFiles = useMemo<ParsedFile[]>(() => {
    if (diffPatch) return parsePatch(diffPatch);
    if (!hasFiles) return [];
    return [{ oldName, newName, ...computeDiff(oldContent, newContent) }];
  }, [diffPatch, hasFiles, oldContent, newContent, oldName, newName]);

  if (parsedFiles.length === 0) {
    return (
      <p
        data-slot="diff-viewer"
        className={cn("rounded-card bg-inset px-3 py-2.5 text-[12.5px] text-ink-3", className)}
      >
        No diff content provided
      </p>
    );
  }

  return (
    <div
      data-slot="diff-viewer"
      data-view-mode={viewMode}
      data-variant={variant ?? "default"}
      data-size={size ?? "default"}
      className={cn(diffViewerVariants({ variant, size }), className)}
    >
      {parsedFiles.map((file, fileIndex) => (
        <div key={fileIndex} data-slot="diff-viewer-file">
          <DiffViewerHeader
            oldName={file.oldName}
            newName={file.newName}
            additions={file.additions}
            deletions={file.deletions}
            showIcon={showIcon}
            showStats={showStats}
          />
          <DiffFileLines file={file} viewMode={viewMode} showLineNumbers={showLineNumbers} />
        </div>
      ))}
    </div>
  );
}

DiffViewer.displayName = "DiffViewer";

export type { ParsedLine, ParsedFile };

export { DiffViewer, diffViewerVariants, parsePatch, computeDiff };

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, type ChangedFile } from "@/lib/api";
import { langForPath } from "@/lib/lang";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { DiffViewer } from "@/components/assistant-ui/diff-viewer";
import { CodeBlock } from "@/components/ai-elements/code-block";
import {
  FileTree,
  FileTreeFile,
  FileTreeFolder,
} from "@/components/ai-elements/file-tree";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  ArrowLeft01Icon,
  EyeIcon,
  GitPullRequestIcon,
} from "@hugeicons/core-free-icons";

type Tab = "all" | "changes";

const MIN_WIDTH = 320;
const DEFAULT_WIDTH = 384; 
const WIDTH_KEY = "changesPanelWidth";

type TreeNode = { name: string; path: string; dir: boolean; children: TreeNode[] };

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", dir: true, children: [] };
  for (const p of paths) {
    const parts = p.split("/");
    let cur = root;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let next = cur.children.find((c) => c.name === part);
      if (!next) {
        next = { name: part, path, dir: i < parts.length - 1, children: [] };
        cur.children.push(next);
      }
      cur = next;
    });
  }
  const sort = (node: TreeNode) => {
    node.children.sort((a, b) =>
      a.dir !== b.dir ? (a.dir ? -1 : 1) : a.name.localeCompare(b.name),
    );
    node.children.forEach(sort);
  };
  sort(root);
  return root.children;
}

function renderTree(nodes: TreeNode[]): ReactNode {
  return nodes.map((n) =>
    n.dir ? (
      <FileTreeFolder key={n.path} path={n.path} name={n.name}>
        {renderTree(n.children)}
      </FileTreeFolder>
    ) : (
      <FileTreeFile key={n.path} path={n.path} name={n.name} />
    ),
  );
}

function PathLabel({ path }: { path: string }) {
  const i = path.lastIndexOf("/");
  const dir = i >= 0 ? path.slice(0, i + 1) : "";
  const name = i >= 0 ? path.slice(i + 1) : path;
  return (
    <span className="truncate font-mono text-xs">
      {dir && <span className="text-muted-foreground">{dir}</span>}
      <span className="text-foreground">{name}</span>
    </span>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-sm transition-colors",
        active
          ? "bg-muted/80 text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function FileStatusIcon({ status }: { status: ChangedFile["status"] }) {
  const color =
    status === "added"
      ? "bg-emerald-500/20 ring-emerald-500/50 [&>span]:bg-emerald-500"
      : status === "deleted"
        ? "bg-red-500/20 ring-red-500/50 [&>span]:bg-red-500"
        : "bg-yellow-500/20 ring-yellow-500/50 [&>span]:bg-yellow-500";
  return (
    <span
      className={cn(
        "flex size-3.5 shrink-0 items-center justify-center rounded-[3px] ring-1",
        color,
      )}
    >
      <span className="size-1 rounded-full" />
    </span>
  );
}

function DetailHeader({ path, onBack }: { path: string; onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="flex items-center gap-1.5 border-b px-3 py-2 text-left hover:bg-muted/50"
    >
      <HugeiconsIcon icon={ArrowLeft01Icon} className="size-4 shrink-0" />
      <PathLabel path={path} />
    </button>
  );
}

function FileDiffView({
  conversationId,
  path,
  onBack,
}: {
  conversationId: string;
  path: string;
  onBack: () => void;
}) {
  const [patch, setPatch] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .fileDiff(conversationId, path)
      .then((d) => active && setPatch(d.patch))
      .catch(() => active && setPatch(""));
    return () => {
      active = false;
    };
  }, [conversationId, path]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <DetailHeader path={path} onBack={onBack} />
      <ScrollArea className="min-h-0 flex-1">
        {patch === null ? (
          <p className="text-muted-foreground p-3 text-xs">Loading diff…</p>
        ) : patch ? (
          <DiffViewer patch={patch} viewMode="unified" />
        ) : (
          <p className="text-muted-foreground p-3 text-xs">No changes to show.</p>
        )}
      </ScrollArea>
    </div>
  );
}

function FileContentView({
  conversationId,
  path,
  onBack,
}: {
  conversationId: string;
  path: string;
  onBack: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .fileContent(conversationId, path)
      .then((d) => active && setContent(d.content))
      .catch(() => active && setContent(""));
    return () => {
      active = false;
    };
  }, [conversationId, path]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <DetailHeader path={path} onBack={onBack} />
      <ScrollArea className="min-h-0 flex-1">
        {content === null ? (
          <p className="text-muted-foreground p-3 text-xs">Loading…</p>
        ) : (
          <CodeBlock code={content} language={langForPath(path)} />
        )}
      </ScrollArea>
    </div>
  );
}

function FileRow({
  path,
  status,
  selected,
  onClick,
  trailing,
}: {
  path: string;
  status: ChangedFile["status"];
  selected?: boolean;
  onClick: () => void;
  trailing?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "mx-2 flex w-[calc(100%-1rem)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
        selected ? "bg-[#2a2624]" : "hover:bg-[#2a2624]/70",
      )}
    >
      <PathLabel path={path} />
      <span className="ml-auto flex shrink-0 items-center gap-2">
        {trailing}
        <FileStatusIcon status={status} />
      </span>
    </button>
  );
}

export function ChangesPanel({
  conversationId,
  changes,
  selectedPath,
  onSelectPath,
  onClose,
}: {
  conversationId: string;
  changes: ChangedFile[];
  selectedPath: string | null;
  onSelectPath: (path: string | null) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("changes");
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [allFiles, setAllFiles] = useState<string[] | null>(null);

  const widthRef = useRef(DEFAULT_WIDTH);
  const dragging = useRef(false);

  useEffect(() => {
    const saved = Number(localStorage.getItem(WIDTH_KEY));
    if (saved) {
      widthRef.current = saved;
      setWidth(saved);
    }
  }, []);

  const onHandleDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (!dragging.current) return;
      const max = window.innerWidth * 0.7;
      const next = Math.min(Math.max(window.innerWidth - e.clientX, MIN_WIDTH), max);
      widthRef.current = next;
      setWidth(next);
    }
    function onUp() {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem(WIDTH_KEY, String(Math.round(widthRef.current)));
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  useEffect(() => {
    if (tab !== "all") return;
    let active = true;
    api
      .files(conversationId)
      .then((f) => active && setAllFiles(f))
      .catch(() => active && setAllFiles([]));
    return () => {
      active = false;
    };
  }, [tab, conversationId, changes]);

  const changed = selectedPath
    ? changes.find((c) => c.path === selectedPath)
    : undefined;

  const tree = useMemo(() => buildTree(allFiles ?? []), [allFiles]);
  const fileSet = useMemo(() => new Set(allFiles ?? []), [allFiles]);
  const topFolders = useMemo(
    () => new Set(tree.filter((n) => n.dir).map((n) => n.path)),
    [tree],
  );

  return (
    <aside
      style={{ width }}
      className="relative flex shrink-0 flex-col border-l bg-background"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize files panel"
        onPointerDown={onHandleDown}
        className="absolute top-0 left-0 z-10 h-full w-1.5 -translate-x-1/2 cursor-col-resize hover:bg-primary/30 active:bg-primary/40"
      />
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-emerald-900/40 bg-[#1b2b1e] px-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="shrink-0 rounded-md border border-emerald-500/35 px-2 py-0.5 text-xs font-medium text-emerald-400">
            PR #126
          </span>
          <div className="flex min-w-0 items-center gap-1.5 text-emerald-400">
            <HugeiconsIcon icon={GitPullRequestIcon} className="size-4 shrink-0" />
            <span className="truncate text-sm">Ready for review</span>
          </div>
        </div>
        <button
          type="button"
          className="shrink-0 rounded-md bg-black/45 px-3 py-1 text-sm text-white transition-colors hover:bg-black/60"
        >
          Create PR
        </button>
      </div>

      <div className="flex items-center justify-between border-b border-border/40 px-3 py-2">
        <div className="flex items-center gap-1">
          <TabButton active={tab === "all"} onClick={() => setTab("all")}>
            All files
          </TabButton>
          <TabButton active={tab === "changes"} onClick={() => setTab("changes")}>
            Changes
            {changes.length > 0 && (
              <span
                className={cn(
                  "ml-1",
                  tab === "changes" ? "text-muted-foreground" : "text-muted-foreground/70",
                )}
              >
                {changes.length}
              </span>
            )}
          </TabButton>
          
        </div>
      </div>
      {selectedPath ? (
        changed ? (
          <FileDiffView
            key={selectedPath}
            conversationId={conversationId}
            path={selectedPath}
            onBack={() => onSelectPath(null)}
          />
        ) : (
          <FileContentView
            key={selectedPath}
            conversationId={conversationId}
            path={selectedPath}
            onBack={() => onSelectPath(null)}
          />
        )
      ) : tab === "all" ? (
        <ScrollArea className="min-h-0 flex-1">
          {allFiles === null ? (
            <p className="text-muted-foreground p-3 text-xs">Loading…</p>
          ) : allFiles.length === 0 ? (
            <p className="text-muted-foreground p-5 text-xs">No files.</p>
          ) : (
            <FileTree
              className="rounded-none border-0 text-xs"
              selectedPath={selectedPath ?? undefined}
              defaultExpanded={topFolders}
              onSelect={(p) => fileSet.has(p) && onSelectPath(p)}
            >
              {renderTree(tree)}
            </FileTree>
          )}
        </ScrollArea>
      ) : changes.length === 0 ? (
        <p className="text-muted-foreground p-5 text-xs">No changes yet.</p>
      ) : (
        <ScrollArea className="min-h-0 flex-1">
          <div className="py-1">
            {changes.map((file) => (
              <FileRow
                key={file.path}
                path={file.path}
                status={file.status}
                selected={selectedPath === file.path}
                onClick={() => onSelectPath(file.path)}
                trailing={
                  <span className="font-mono text-xs">
                    {file.additions > 0 && (
                      <span className="text-emerald-500">+{file.additions}</span>
                    )}
                    {file.deletions > 0 && (
                      <span className="text-destructive"> −{file.deletions}</span>
                    )}
                  </span>
                }
              />
            ))}
          </div>
        </ScrollArea>
      )}
    </aside>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
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
  ArrowExpand01Icon,
  ArrowLeft01Icon,
  ArrowShrink01Icon,
  PanelRightIcon,
} from "@hugeicons/core-free-icons";

type Tab = "all" | "changes";

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
        "rounded px-2 py-1 text-sm",
        active
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
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
  onClick,
  trailing,
}: {
  path: string;
  onClick: () => void;
  trailing?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/50"
    >
      <PathLabel path={path} />
      {trailing && <span className="ml-auto shrink-0">{trailing}</span>}
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
  const [expanded, setExpanded] = useState(false);
  const [allFiles, setAllFiles] = useState<string[] | null>(null);

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
      className={cn(
        "flex shrink-0 flex-col border-l bg-background",
        expanded ? "w-[42rem] max-w-[60vw]" : "w-96",
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <button
          type="button"
          onClick={onClose}
          aria-label="Hide files panel"
          className="rounded p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
        >
          <HugeiconsIcon icon={PanelRightIcon} className="size-4" />
        </button>
        <div className="flex items-center gap-1">
          <TabButton active={tab === "all"} onClick={() => setTab("all")}>
            All files
          </TabButton>
          <TabButton active={tab === "changes"} onClick={() => setTab("changes")}>
            Changes
            {changes.length > 0 && (
              <span className="ml-1 text-muted-foreground">{changes.length}</span>
            )}
          </TabButton>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? "Shrink panel" : "Expand panel"}
          className="ml-auto rounded p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
        >
          <HugeiconsIcon
            icon={expanded ? ArrowShrink01Icon : ArrowExpand01Icon}
            className="size-4"
          />
        </button>
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
            <p className="text-muted-foreground p-3 text-xs">No files.</p>
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
        <p className="text-muted-foreground p-3 text-xs">No changes yet.</p>
      ) : (
        <ScrollArea className="min-h-0 flex-1">
          <div className="py-1">
            {changes.map((file) => (
              <FileRow
                key={file.path}
                path={file.path}
                onClick={() => onSelectPath(file.path)}
                trailing={
                  <span className="font-mono text-xs">
                    {file.additions > 0 && (
                      <span className="text-emerald-600">+{file.additions}</span>
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

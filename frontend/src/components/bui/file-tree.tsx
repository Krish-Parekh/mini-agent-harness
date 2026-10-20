"use client";

import { memo, useCallback, useMemo, useState } from "react";
import { ChevronRightIcon, FileIcon, FolderIcon, FolderOpenIcon } from "lucide-react";

import { GlideMenu } from "@/components/bui/glide-menu";
import { cn } from "@/lib/utils";

type TreeNode = { name: string; path: string; dir: boolean; children: TreeNode[] };

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", dir: true, children: [] };
  const index = new Map<string, TreeNode>();
  for (const p of paths) {
    const parts = p.split("/");
    let cur = root;
    let path = "";
    parts.forEach((part, i) => {
      path = path ? `${path}/${part}` : part;
      let next = index.get(path);
      if (!next) {
        next = { name: part, path, dir: i < parts.length - 1, children: [] };
        index.set(path, next);
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

const ROW =
  "relative z-10 mx-2 flex h-7 w-[calc(100%-1rem)] items-center gap-1.5 rounded-[7px] pr-2 text-left text-[13px] transition-[background-color,color,transform] duration-150 active:scale-[0.99]";

const TreeRows = memo(function TreeRows({
  nodes,
  depth,
  expanded,
  selectedPath,
  onToggle,
  onSelect,
}: {
  nodes: TreeNode[];
  depth: number;
  expanded: Set<string>;
  selectedPath: string | null;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}) {
  return nodes.map((node) => {
    const pad = { paddingLeft: 8 + depth * 14 };
    if (node.dir) {
      const open = expanded.has(node.path);
      return (
        <div key={node.path} role="none">
          <button
            data-menu-row
            type="button"
            role="treeitem"
            aria-level={depth + 1}
            aria-expanded={open}
            aria-selected={false}
            onClick={() => onToggle(node.path)}
            className={cn(ROW, "text-ink-2 hover:text-ink")}
            style={pad}
          >
            <ChevronRightIcon
              className={cn(
                "size-3.5 shrink-0 text-ink-3 transition-transform duration-150",
                open && "rotate-90",
              )}
            />
            {open ? (
              <FolderOpenIcon className="size-3.5 shrink-0 text-ink-3" />
            ) : (
              <FolderIcon className="size-3.5 shrink-0 text-ink-3" />
            )}
            <span className="min-w-0 flex-1 truncate font-medium">{node.name}</span>
          </button>
          {open && (
            <div role="group">
              <TreeRows
                nodes={node.children}
                depth={depth + 1}
                expanded={expanded}
                selectedPath={selectedPath}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            </div>
          )}
        </div>
      );
    }
    const active = node.path === selectedPath;
    return (
      <button
        key={node.path}
        data-menu-row
        type="button"
        role="treeitem"
        aria-level={depth + 1}
        aria-selected={active}
        onClick={() => onSelect(node.path)}
        className={cn(
          ROW,
          active
            ? "bg-hover-2 text-ink group-hover/glide-menu:bg-transparent"
            : "text-ink-2 hover:text-ink",
        )}
        style={pad}
      >
        <span className="size-3.5 shrink-0" />
        <FileIcon className="size-3.5 shrink-0 text-ink-3" />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
      </button>
    );
  });
});

export function FileTree({
  paths,
  selectedPath,
  onSelect,
  label = "Files",
}: {
  paths: string[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  label?: string;
}) {
  const tree = useMemo(() => buildTree(paths), [paths]);
  const [toggled, setToggled] = useState<Set<string>>(() => new Set());
  const expanded = useMemo(() => {
    const open = new Set<string>();
    for (const node of tree) if (node.dir) open.add(node.path);
    for (const path of toggled) {
      if (open.has(path)) open.delete(path);
      else open.add(path);
    }
    return open;
  }, [tree, toggled]);

  const onToggle = useCallback((path: string) => {
    setToggled((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  return (
    <div role="tree" aria-label={label} className="py-1.5">
      <GlideMenu
        className="flex flex-col gap-px"
        highlightClassName="inset-x-2 rounded-[7px] bg-hover-2"
      >
        <TreeRows
          nodes={tree}
          depth={0}
          expanded={expanded}
          selectedPath={selectedPath}
          onToggle={onToggle}
          onSelect={onSelect}
        />
      </GlideMenu>
    </div>
  );
}

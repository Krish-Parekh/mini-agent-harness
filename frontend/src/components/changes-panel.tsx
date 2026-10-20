"use client";

import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  ArrowLeft01Icon,
  Cancel01Icon,
  GitPullRequestIcon,
} from "@hugeicons/core-free-icons";

import { api, type ChangedFile } from "@/lib/api";
import { langForPath } from "@/lib/lang";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Spinner } from "@/components/ui/spinner";
import { DiffViewer } from "@/components/bui/diff-viewer";
import { CodeBlock } from "@/components/bui/code-block";
import { FileTree } from "@/components/bui/file-tree";
import { GlideMenu } from "@/components/bui/glide-menu";
import { LoadingState } from "@/components/bui/loading-state";
import { Pill } from "@/components/bui/button";
import { ValuePill } from "@/components/bui/value-pill";

type Tab = "all" | "changes";
type View = "diff" | "code";

const MIN_WIDTH = 320;
const DEFAULT_WIDTH = 384;
const WIDTH_KEY = "changesPanelWidth";

const widthListeners = new Set<() => void>();
let storedWidth: number | null = null;

function readWidth() {
  if (storedWidth === null) {
    try {
      storedWidth = Number(localStorage.getItem(WIDTH_KEY)) || DEFAULT_WIDTH;
    } catch {
      storedWidth = DEFAULT_WIDTH;
    }
  }
  return storedWidth;
}

function writeWidth(width: number) {
  storedWidth = width;
  try {
    localStorage.setItem(WIDTH_KEY, String(width));
  } catch {}
  widthListeners.forEach((listener) => listener());
}

function subscribeWidth(listener: () => void) {
  widthListeners.add(listener);
  return () => {
    widthListeners.delete(listener);
  };
}

const serverWidth = () => DEFAULT_WIDTH;

const STATUS = {
  added: { letter: "A", tone: "bg-green-tint text-green" },
  modified: { letter: "M", tone: "bg-orange-tint text-orange" },
  deleted: { letter: "D", tone: "bg-red-tint text-red" },
} as const;

function PathLabel({ path }: { path: string }) {
  const i = path.lastIndexOf("/");
  const dir = i >= 0 ? path.slice(0, i + 1) : "";
  const name = i >= 0 ? path.slice(i + 1) : path;
  return (
    <span className="min-w-0 truncate font-mono text-[12px]">
      {dir && <span className="text-ink-3">{dir}</span>}
      <span className="text-ink">{name}</span>
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
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-chip px-2 py-[3px] text-[13px] text-ink transition-[background-color,opacity] duration-100",
        active ? "bg-field" : "opacity-50 hover:opacity-75",
      )}
    >
      {children}
    </button>
  );
}

function StatusMark({ status }: { status: ChangedFile["status"] }) {
  const s = STATUS[status];
  return (
    <span
      title={status}
      className={cn(
        "inline-flex size-4 shrink-0 items-center justify-center rounded-[4px] font-mono text-[10px] font-semibold",
        s.tone,
      )}
    >
      <span aria-hidden>{s.letter}</span>
      <span className="sr-only">{status}</span>
    </span>
  );
}

function PanelMessage({ children }: { children: ReactNode }) {
  return <p className="px-4 py-5 text-[12.5px] text-ink-3">{children}</p>;
}

function DetailHeader({
  path,
  onBack,
  children,
}: {
  path: string;
  onBack: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line px-1.5">
      <button
        type="button"
        onClick={onBack}
        aria-label="Back to files"
        className="flex size-7 shrink-0 items-center justify-center rounded-chip text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover hover:text-ink active:scale-[0.96]"
      >
        <HugeiconsIcon icon={ArrowLeft01Icon} className="size-4" />
      </button>
      <PathLabel path={path} />
      {children && <div className="ml-auto flex shrink-0 items-center">{children}</div>}
    </div>
  );
}

function FileDiffView({
  conversationId,
  path,
  revision,
}: {
  conversationId: string;
  path: string;
  revision: number;
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
  }, [conversationId, path, revision]);

  if (patch === null) return <LoadingState label="Loading diff" className="px-4 py-5" />;
  if (!patch) return <PanelMessage>No changes to show.</PanelMessage>;
  return <DiffViewer patch={patch} viewMode="unified" variant="ghost" />;
}

function FileContentView({
  conversationId,
  path,
  revision,
}: {
  conversationId: string;
  path: string;
  revision: number;
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
  }, [conversationId, path, revision]);

  if (content === null) return <LoadingState label="Loading file" className="px-4 py-5" />;
  return <CodeBlock code={content} language={langForPath(path)} filename={path} flush />;
}

function FileDetail({
  conversationId,
  path,
  changed,
  revision,
  onBack,
}: {
  conversationId: string;
  path: string;
  changed: ChangedFile | undefined;
  revision: number;
  onBack: () => void;
}) {
  const [view, setView] = useState<View>("diff");
  const canToggle = changed !== undefined && changed.status !== "deleted";
  const mode: View = !changed ? "code" : canToggle ? view : "diff";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <DetailHeader path={path} onBack={onBack}>
        {canToggle && (
          <>
            <TabButton active={mode === "diff"} onClick={() => setView("diff")}>
              Diff
            </TabButton>
            <TabButton active={mode === "code"} onClick={() => setView("code")}>
              Code
            </TabButton>
          </>
        )}
      </DetailHeader>
      <ScrollArea className="min-h-0 flex-1">
        {mode === "diff" ? (
          <FileDiffView conversationId={conversationId} path={path} revision={revision} />
        ) : (
          <FileContentView conversationId={conversationId} path={path} revision={revision} />
        )}
      </ScrollArea>
    </div>
  );
}

function ChangeRow({
  file,
  selected,
  onSelect,
}: {
  file: ChangedFile;
  selected: boolean;
  onSelect: (path: string) => void;
}) {
  return (
    <button
      data-menu-row
      type="button"
      onClick={() => onSelect(file.path)}
      className={cn(
        "relative z-10 mx-2 flex h-8 w-[calc(100%-1rem)] items-center gap-2 rounded-[7px] px-2 text-left transition-[background-color,transform] duration-150 active:scale-[0.99]",
        selected && "bg-hover-2 group-hover/glide-menu:bg-transparent",
      )}
    >
      <PathLabel path={file.path} />
      <span className="ml-auto flex shrink-0 items-center gap-1">
        {file.additions > 0 && <ValuePill tone="green">+{file.additions}</ValuePill>}
        {file.deletions > 0 && <ValuePill tone="red">−{file.deletions}</ValuePill>}
        <StatusMark status={file.status} />
      </span>
    </button>
  );
}

function PrBar({
  pr,
  changeCount,
  running,
  creating,
  error,
  onSync,
}: {
  pr: { number: number; url: string } | null;
  changeCount: number;
  running: boolean;
  creating: boolean;
  error: boolean;
  onSync: () => void;
}) {
  const tone = creating ? "brand" : changeCount > 0 ? "orange" : "green";
  return (
    <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-line px-3">
      {pr !== null ? (
        <a
          href={pr.url}
          target="_blank"
          rel="noreferrer"
          className="group/pr flex min-w-0 items-center gap-2"
        >
          <ValuePill tone={tone} className="h-5 shrink-0 px-2">
            PR #{pr.number}
          </ValuePill>
          <span className="flex min-w-0 items-center gap-1.5 text-ink-2 transition-colors group-hover/pr:text-ink">
            <HugeiconsIcon icon={GitPullRequestIcon} className="size-4 shrink-0" />
            <span className="truncate text-[13px]">
              {changeCount > 0 ? "Changes to push" : "View on GitHub"}
            </span>
          </span>
        </a>
      ) : (
        <div className={cn("flex min-w-0 items-center gap-1.5", error ? "text-red" : "text-ink-2")}>
          <HugeiconsIcon icon={GitPullRequestIcon} className="size-4 shrink-0" />
          <span className="truncate text-[13px]">
            {error
              ? "Couldn't sync PR. Try again."
              : `${changeCount} file${changeCount === 1 ? "" : "s"} changed`}
          </span>
        </div>
      )}
      {changeCount > 0 && (
        <Pill variant="primary" size="sm" onClick={onSync} disabled={running || creating} className="shrink-0">
          {creating ? (
            <>
              {pr !== null ? "Updating" : "Creating"}
              <Spinner className="size-3.5" />
            </>
          ) : running ? (
            <>
              Working
              <Spinner className="size-3.5" />
            </>
          ) : pr !== null ? (
            "Update PR"
          ) : (
            "Create PR"
          )}
        </Pill>
      )}
    </div>
  );
}

export const ChangesPanel = memo(function ChangesPanel({
  conversationId,
  changes,
  prNumber,
  prUrl,
  running,
  selectedPath,
  onSelectPath,
  onClose,
  onSynced,
  revision,
}: {
  conversationId: string;
  changes: ChangedFile[];
  prNumber: number | null;
  prUrl: string | null;
  running: boolean;
  selectedPath: string | null;
  onSelectPath: (path: string | null) => void;
  onClose: () => void;
  onSynced?: () => void;
  revision: number;
}) {
  const [tab, setTab] = useState<Tab>("changes");
  const [allFiles, setAllFiles] = useState<string[] | null>(null);
  const [createdPr, setCreatedPr] = useState<{ number: number; url: string } | null>(null);
  const [creatingPr, setCreatingPr] = useState(false);
  const [prError, setPrError] = useState(false);
  const pr =
    createdPr ?? (prNumber != null && prUrl ? { number: prNumber, url: prUrl } : null);

  const syncPr = useCallback(async () => {
    setCreatingPr(true);
    setPrError(false);
    try {
      const info = await api.createPr(conversationId);
      if (info.pr_number != null && info.pr_url)
        setCreatedPr({ number: info.pr_number, url: info.pr_url });
      onSynced?.();
    } catch {
      setPrError(true);
    } finally {
      setCreatingPr(false);
    }
  }, [conversationId, onSynced]);

  const width = useSyncExternalStore(subscribeWidth, readWidth, serverWidth);
  const asideRef = useRef<HTMLElement>(null);
  const dragWidth = useRef<number | null>(null);

  const onHandleDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragWidth.current = asideRef.current?.offsetWidth ?? DEFAULT_WIDTH;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const onHandleMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (dragWidth.current === null || !asideRef.current) return;
    const max = window.innerWidth * 0.7;
    const next = Math.min(Math.max(window.innerWidth - e.clientX, MIN_WIDTH), max);
    dragWidth.current = next;
    asideRef.current.style.width = `${next}px`;
  }, []);

  const onHandleUp = useCallback(() => {
    if (dragWidth.current === null) return;
    const next = Math.round(dragWidth.current);
    dragWidth.current = null;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    writeWidth(next);
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

  const changed = selectedPath ? changes.find((c) => c.path === selectedPath) : undefined;
  const back = useCallback(() => onSelectPath(null), [onSelectPath]);

  return (
    <aside
      ref={asideRef}
      style={{ width }}
      className="relative flex shrink-0 flex-col border-l border-line bg-surface"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize files panel"
        onPointerDown={onHandleDown}
        onPointerMove={onHandleMove}
        onPointerUp={onHandleUp}
        onPointerCancel={onHandleUp}
        className="absolute top-0 left-0 z-20 h-full w-1.5 -translate-x-1/2 cursor-col-resize transition-colors duration-150 hover:bg-line-strong active:bg-brand/40"
      />
      {(pr !== null || changes.length > 0) && (
        <PrBar
          pr={pr}
          changeCount={changes.length}
          running={running}
          creating={creatingPr}
          error={prError}
          onSync={syncPr}
        />
      )}

      <div className="flex shrink-0 items-center justify-between border-b border-line p-1.5">
        <div className="flex items-center">
          <TabButton active={tab === "all"} onClick={() => setTab("all")}>
            All files
          </TabButton>
          <TabButton active={tab === "changes"} onClick={() => setTab("changes")}>
            Changes
            {changes.length > 0 && (
              <span className="text-[12px] text-ink-3 tabular-nums">{changes.length}</span>
            )}
          </TabButton>
        </div>
        <button
          type="button"
          aria-label="Close files panel"
          onClick={onClose}
          className="flex size-6 items-center justify-center rounded-chip text-ink-3 transition-colors duration-100 hover:bg-hover hover:text-ink-2"
        >
          <HugeiconsIcon icon={Cancel01Icon} className="size-3.5" />
        </button>
      </div>

      {selectedPath ? (
        <FileDetail
          key={selectedPath}
          conversationId={conversationId}
          path={selectedPath}
          changed={changed}
          revision={revision}
          onBack={back}
        />
      ) : tab === "all" ? (
        <ScrollArea className="min-h-0 flex-1">
          {allFiles === null ? (
            <LoadingState label="Loading files" className="px-4 py-5" />
          ) : allFiles.length === 0 ? (
            <PanelMessage>No files.</PanelMessage>
          ) : (
            <FileTree paths={allFiles} selectedPath={selectedPath} onSelect={onSelectPath} />
          )}
        </ScrollArea>
      ) : changes.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 pb-10 text-center">
          <span className="flex size-9 items-center justify-center rounded-control bg-field text-ink-3 shadow-hairline">
            <HugeiconsIcon icon={GitPullRequestIcon} className="size-4" />
          </span>
          <p className="text-[13px] font-medium text-ink-2">No changes yet</p>
          <p className="text-[12px] text-ink-3">Edits the agent makes will show up here.</p>
        </div>
      ) : (
        <ScrollArea className="min-h-0 flex-1">
          <GlideMenu
            className="flex flex-col gap-px py-1.5"
            highlightClassName="inset-x-2 rounded-[7px] bg-hover-2"
          >
            {changes.map((file) => (
              <ChangeRow
                key={file.path}
                file={file}
                selected={selectedPath === file.path}
                onSelect={onSelectPath}
              />
            ))}
          </GlideMenu>
        </ScrollArea>
      )}
    </aside>
  );
});

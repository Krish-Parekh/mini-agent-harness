import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BrainIcon,
  CircleCheckIcon,
  FileIcon,
  FileSearchIcon,
  FilePenIcon,
  FilePlusIcon,
  GlobeIcon,
  KeyboardIcon,
  ListChecksIcon,
  LibraryIcon,
  NetworkIcon,
  SearchIcon,
  TerminalIcon,
} from "lucide-react";
import { diffLines } from "diff";
import type { ActionEvent, ObservationEvent } from "@/lib/events";
import { SourceList, type Source, uniqueSources } from "@/components/bui/chat-message";
import { formatInstalls } from "@/components/bui/skill-proposal-card";
import type { DiffStat } from "@/components/bui/tool-chips";
import { ValuePill } from "@/components/bui/value-pill";
import { cn } from "@/lib/utils";

export type FileChange = {
  path: string;
  oldContent: string;
  newContent: string;
  kind: "file" | "snippet";
};

export function ScrollablePreview({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("max-h-64 overflow-y-auto rounded-control", className)}>{children}</div>
  );
}

export type ToolView = {
  icon: LucideIcon;
  verb: string;
  target?: string;
  mono?: boolean;
  filePath?: string;
  fileChange?: FileChange | null;
  preview?: ReactNode;
};

type Args = Record<string, unknown>;
type ToolRenderer = (args: Args) => ToolView;

function countLines(text: string): number {
  if (!text) return 0;
  return text.replace(/\n$/, "").split("\n").length;
}

export function diffStat(change: FileChange): DiffStat {
  if (!change.oldContent) return { add: countLines(change.newContent), del: 0 };
  let add = 0;
  let del = 0;
  for (const part of diffLines(change.oldContent, change.newContent)) {
    if (part.added) add += part.count ?? countLines(part.value);
    else if (part.removed) del += part.count ?? countLines(part.value);
  }
  return { add, del };
}

function CodePreview({ children }: { children: string }) {
  return (
    <ScrollablePreview>
      <pre className="overflow-x-auto rounded-control bg-inset px-2.5 py-2 font-mono text-[11.5px] leading-[1.6] text-ink-2 shadow-hairline">
        {children}
      </pre>
    </ScrollablePreview>
  );
}

const TOOL_VIEWS: Record<string, ToolRenderer> = {
  terminal: (a) => {
    const command = String(a.command ?? "");
    const description = String(a.description ?? "").trim();
    if (a.is_input) {
      return {
        icon: KeyboardIcon,
        verb: command ? "Send input" : "Read output",
        target: command || undefined,
        mono: true,
      };
    }
    return {
      icon: TerminalIcon,
      verb: a.reset ? "Reset terminal" : "Terminal",
      target: description || command || undefined,
      mono: !description,
      preview: command ? <CodePreview>{command}</CodePreview> : undefined,
    };
  },
  file_edit: (a) => {
    const path = String(a.path ?? "file");
    if (a.command === "view") {
      return { icon: FileIcon, verb: "Read", target: path, mono: true, filePath: path };
    }
    if (a.command === "create") {
      return {
        icon: FilePlusIcon,
        verb: "Create",
        target: path,
        mono: true,
        filePath: path,
        fileChange: {
          path,
          oldContent: "",
          newContent: String(a.content ?? ""),
          kind: "file",
        },
      };
    }
    return {
      icon: FilePenIcon,
      verb: "Update",
      target: path,
      mono: true,
      filePath: path,
      fileChange: {
        path,
        oldContent: String(a.old_str ?? ""),
        newContent: String(a.new_str ?? ""),
        kind: "snippet",
      },
    };
  },
  finish: () => ({ icon: CircleCheckIcon, verb: "Finished" }),
  fanout: (a) => {
    const tasks = (a.tasks as { title?: string }[] | undefined) ?? [];
    return {
      icon: NetworkIcon,
      verb: "Fan-out",
      target:
        tasks.length > 0
          ? `${tasks.length} agent${tasks.length === 1 ? "" : "s"}`
          : "agents",
    };
  },
  update_plan: (a) => ({
    icon: ListChecksIcon,
    verb: a.status === "done" ? "Step done" : "Step started",
    target: `step ${a.step ?? "?"}`,
  }),
  web_search: (a) => ({
    icon: SearchIcon,
    verb: "Web search",
    target: String(a.query ?? ""),
  }),
  fetch_url: (a) => ({
    icon: GlobeIcon,
    verb: "Fetch URL",
    target: String(a.url ?? ""),
    mono: true,
  }),
  skill: (a) => ({
    icon: LibraryIcon,
    verb: "Use skill",
    target: String(a.name ?? ""),
    mono: true,
  }),
  find_skills: (a) => ({
    icon: SearchIcon,
    verb: "Search skills.sh",
    target: String(a.query ?? ""),
  }),
  web_research: (a) => ({
    icon: SearchIcon,
    verb: "Web research",
    target: String(a.description ?? a.prompt ?? "research"),
  }),
  grep: (a) => ({
    icon: SearchIcon,
    verb: "Grep",
    target: `${a.pattern ?? ""}${a.path && a.path !== "." ? ` in ${a.path}` : ""}`,
    mono: true,
  }),
  glob: (a) => ({
    icon: FileSearchIcon,
    verb: "Glob",
    target: String(a.pattern ?? ""),
    mono: true,
  }),
  memory: (a) => ({
    icon: BrainIcon,
    verb: MEMORY_VERBS[String(a.command)] ?? "Memory",
    target: String(a.path ?? a.old_path ?? ""),
    mono: true,
  }),
};

const MEMORY_VERBS: Record<string, string> = {
  view: "Recall",
  create: "Saved memory",
  str_replace: "Updated memory",
  insert: "Updated memory",
  delete: "Forgot",
  rename: "Renamed memory",
};

export function toolView(ev: ActionEvent): ToolView {
  const render = TOOL_VIEWS[ev.tool_name];
  if (render) return render(ev.arguments ?? {});
  return { icon: FileIcon, verb: ev.tool_name || "Tool" };
}

type WebSearchResultDetail = {
  title?: string;
  url: string;
  snippet?: string;
};

export function observationSources(toolName: string, obs: ObservationEvent): Source[] {
  if (toolName !== "web_search" || obs.error || !obs.details) return [];
  const results = (obs.details.results as WebSearchResultDetail[] | undefined) ?? [];
  return uniqueSources(results);
}

type SkillSearchHit = { id: string; installs: number; description: string };

const SKILL_HIT = /^- (\S+) \(([\d,]+) installs?\):?\s*(.*)$/;

function parseSkillHits(content: string): SkillSearchHit[] {
  const hits: SkillSearchHit[] = [];
  for (const line of content.split("\n")) {
    const match = SKILL_HIT.exec(line.trim());
    if (match) {
      hits.push({
        id: match[1],
        installs: Number(match[2].replace(/,/g, "")),
        description: match[3].trim(),
      });
    }
  }
  return hits;
}

function SkillHitList({ content }: { content: string }) {
  const hits = parseSkillHits(content);
  if (hits.length === 0) {
    return <p className="text-[12px] text-ink-3">{content.trim() || "No skills found."}</p>;
  }
  return (
    <ScrollablePreview>
      <ul className="flex flex-col gap-1.5">
        {hits.map((hit) => (
          <li key={hit.id} className="flex min-w-0 flex-col gap-0.5">
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate font-mono text-[12px] text-ink">{hit.id}</span>
              <ValuePill className="shrink-0">{formatInstalls(hit.installs)}</ValuePill>
            </span>
            {hit.description && (
              <span className="line-clamp-2 text-[12px] leading-snug text-ink-3">
                {hit.description}
              </span>
            )}
          </li>
        ))}
      </ul>
    </ScrollablePreview>
  );
}

type TerminalDetails = {
  output?: string;
  exit_code?: number;
  working_dir?: string | null;
};

function tailText(text: string, max = 8000): string {
  return text.length > max ? `…${text.slice(-max)}` : text;
}

function TerminalResult({ details }: { details: TerminalDetails }) {
  const output = details.output?.trim() ?? "";
  const exitCode = details.exit_code ?? -1;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {output && (
        <ScrollablePreview>
          <pre className="whitespace-pre-wrap break-words rounded-control bg-inset px-2.5 py-2 font-mono text-[11.5px] leading-[1.6] text-ink-2 shadow-hairline">
            {tailText(output)}
          </pre>
        </ScrollablePreview>
      )}
      <p className="flex min-w-0 items-center gap-2 text-[12px] text-ink-3">
        {exitCode === -1 ? (
          <ValuePill tone="orange" className="shrink-0">
            Still running
          </ValuePill>
        ) : (
          <ValuePill tone={exitCode === 0 ? "green" : "red"} className="shrink-0">
            exit {exitCode}
          </ValuePill>
        )}
        {details.working_dir && (
          <span className="truncate font-mono">{details.working_dir}</span>
        )}
      </p>
    </div>
  );
}

export function toolObservationDetail(
  toolName: string,
  obs: ObservationEvent,
): ReactNode | undefined {
  if (toolName === "find_skills") {
    return obs.error ? undefined : <SkillHitList content={obs.content ?? ""} />;
  }
  if (toolName === "terminal") {
    return obs.error || !obs.details ? undefined : (
      <TerminalResult details={obs.details as TerminalDetails} />
    );
  }
  const sources = observationSources(toolName, obs);
  if (sources.length === 0) return undefined;
  return <SourceList sources={sources} />;
}

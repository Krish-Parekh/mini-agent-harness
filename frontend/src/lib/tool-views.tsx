import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  CircleCheckIcon,
  FileIcon,
  FilePenIcon,
  FilePlusIcon,
  GlobeIcon,
  ListChecksIcon,
  SearchIcon,
  TerminalIcon,
} from "lucide-react";
import type { ActionEvent, ObservationEvent } from "@/lib/events";
import {
  Avatar,
  AvatarFallback,
  AvatarGroup,
  AvatarGroupCount,
  AvatarImage,
} from "@/components/ui/avatar";
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
    <div className={cn("max-h-64 overflow-y-auto", className)}>{children}</div>
  );
}

export type ToolView = {
  icon: LucideIcon;
  verb: string;
  target?: string;
  filePath?: string;
  fileChange?: FileChange | null;
  preview?: ReactNode;
};

type Args = Record<string, unknown>;
type ToolRenderer = (args: Args) => ToolView;

function hostnameFromUrl(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function faviconUrl(hostname: string): string {
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(hostname)}&sz=16`;
}

function SourceAvatars({ results }: { results: { url: string; title?: string }[] }) {
  const seen = new Set<string>();
  const sources: { host: string; url: string; title?: string }[] = [];
  for (const result of results) {
    const host = hostnameFromUrl(result.url);
    if (seen.has(host)) continue;
    seen.add(host);
    sources.push({ host, url: result.url, title: result.title });
  }
  if (sources.length === 0) return null;

  const max = 6;
  const shown = sources.slice(0, max);
  const overflow = sources.length - max;

  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 px-2.5 py-2">
      <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        Sources
      </p>
      <AvatarGroup className="-space-x-1">
        {shown.map(({ host, url, title }) => (
          <a
            key={host}
            href={url}
            target="_blank"
            rel="noreferrer"
            title={title?.trim() || host}
          >
            <Avatar size="sm" className="size-5 after:border-0">
              <AvatarImage src={faviconUrl(host)} alt={host} />
              <AvatarFallback className="text-[9px] font-medium">
                {host[0]?.toUpperCase() ?? "?"}
              </AvatarFallback>
            </Avatar>
          </a>
        ))}
        {overflow > 0 && (
          <AvatarGroupCount className="size-5 text-[9px]">+{overflow}</AvatarGroupCount>
        )}
      </AvatarGroup>
    </div>
  );
}

export function ExternalUrl({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn("truncate text-primary hover:underline", className)}
    >
      {children}
    </a>
  );
}

const TOOL_VIEWS: Record<string, ToolRenderer> = {
  bash: (a) => {
    const command = String(a.command ?? "");
    return {
      icon: TerminalIcon,
      verb: "Bash",
      target: command,
      preview: (
        <ScrollablePreview>
          <pre className="overflow-x-auto rounded-md bg-muted/50 px-3 py-2 font-mono text-xs">
            {command}
          </pre>
        </ScrollablePreview>
      ),
    };
  },
  file_edit: (a) => {
    const path = String(a.path ?? "file");
    if (a.command === "view") {
      return { icon: FileIcon, verb: "Read", target: path, filePath: path };
    }
    if (a.command === "create") {
      return {
        icon: FilePlusIcon,
        verb: "Create",
        target: path,
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
      icon: FileIcon,
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
  web_search: (a) => {
    const query = String(a.query ?? "");
    return {
      icon: SearchIcon,
      verb: "Web search",
      target: query,
    };
  },
  fetch_url: (a) => {
    const url = String(a.url ?? "");
    return {
      icon: GlobeIcon,
      verb: "Fetch URL",
      target: url,
    };
  },
  web_research: (a) => ({
    icon: SearchIcon,
    verb: "Web research",
    target: String(a.description ?? a.prompt ?? "research"),
  }),
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

export function toolObservationDetail(
  toolName: string,
  obs: ObservationEvent,
): ReactNode | undefined {
  const details = obs.details;
  if (!details) return undefined;

  if (toolName === "web_search") {
    const results = (details.results as WebSearchResultDetail[] | undefined) ?? [];
    if (results.length === 0) return undefined;
    return <SourceAvatars results={results} />;
  }

  if (toolName === "fetch_url") {
    return undefined;
  }

  return undefined;
}

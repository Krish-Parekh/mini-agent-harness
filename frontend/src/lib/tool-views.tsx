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
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
} from "@/components/ai-elements/chain-of-thought";
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

const TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search";

function EndpointRow({
  method,
  endpoint,
}: {
  method: string;
  endpoint: string;
}) {
  return (
    <p className="font-mono text-[11px] text-muted-foreground">
      <span className="text-foreground/70">{method}</span> {endpoint}
    </p>
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
      preview: (
        <ScrollablePreview className="space-y-2">
          <EndpointRow method="POST" endpoint={TAVILY_SEARCH_ENDPOINT} />
          {query ? (
            <p className="text-xs text-muted-foreground">
              query: <span className="text-foreground">{query}</span>
            </p>
          ) : null}
        </ScrollablePreview>
      ),
    };
  },
  fetch_url: (a) => {
    const url = String(a.url ?? "");
    return {
      icon: GlobeIcon,
      verb: "Fetch URL",
      target: url,
      preview: url ? (
        <ScrollablePreview className="space-y-2">
          <EndpointRow method="GET" endpoint={url} />
        </ScrollablePreview>
      ) : undefined,
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
    const endpoint = String(details.endpoint ?? TAVILY_SEARCH_ENDPOINT);
    const method = String(details.method ?? "POST");
    const query = String(details.query ?? "");
    const results = (details.results as WebSearchResultDetail[] | undefined) ?? [];
    const answer =
      typeof details.answer === "string" && details.answer.trim()
        ? details.answer
        : null;

    return (
      <div className="space-y-2 rounded-lg border border-border/60 bg-muted/20 p-3">
        <EndpointRow method={method} endpoint={endpoint} />
        {query ? (
          <p className="text-xs text-muted-foreground">
            query: <span className="text-foreground">{query}</span>
          </p>
        ) : null}
        {answer ? (
          <p className="text-xs leading-relaxed text-foreground">{answer}</p>
        ) : null}
        {results.length > 0 ? (
          <div className="space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Result URLs
            </p>
            <ul className="space-y-2">
              {results.map((result) => (
                <li key={result.url} className="space-y-0.5">
                  <ExternalUrl href={result.url}>
                    {result.title?.trim() || result.url}
                  </ExternalUrl>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {result.url}
                  </p>
                  {result.snippet ? (
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {result.snippet}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            <ChainOfThoughtSearchResults>
              {results.map((result) => {
                let hostname = result.url;
                try {
                  hostname = new URL(result.url).hostname;
                } catch {
                  // keep full URL
                }
                return (
                  <ChainOfThoughtSearchResult key={result.url}>
                    <a href={result.url} target="_blank" rel="noreferrer">
                      {hostname}
                    </a>
                  </ChainOfThoughtSearchResult>
                );
              })}
            </ChainOfThoughtSearchResults>
          </div>
        ) : !obs.error ? (
          <p className="text-xs text-muted-foreground">No result URLs returned.</p>
        ) : null}
      </div>
    );
  }

  if (toolName === "fetch_url") {
    const url = String(details.url ?? "");
    const method = String(details.method ?? "GET");
    if (!url) return undefined;
    return (
      <div className="space-y-2 rounded-lg border border-border/60 bg-muted/20 p-3">
        <EndpointRow method={method} endpoint={url} />
        {!obs.error && obs.content ? (
          <ScrollablePreview>
            <pre className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
              {obs.content.replace(/^url: [^\n]+\ncontent:\n/, "")}
            </pre>
          </ScrollablePreview>
        ) : null}
      </div>
    );
  }

  return undefined;
}

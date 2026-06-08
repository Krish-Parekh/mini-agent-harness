import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  CircleCheckIcon,
  FileIcon,
  FilePenIcon,
  FilePlusIcon,
  TerminalIcon,
} from "lucide-react";
import type { ActionEvent } from "@/lib/events";

export type FileChange = {
  path: string;
  oldContent: string;
  newContent: string;
};

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

const TOOL_VIEWS: Record<string, ToolRenderer> = {
  bash: (a) => {
    const command = String(a.command ?? "");
    return {
      icon: TerminalIcon,
      verb: "Bash",
      target: command,
      preview: (
        <pre className="overflow-x-auto rounded-md bg-muted/50 px-3 py-2 font-mono text-xs">
          {command}
        </pre>
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
        fileChange: { path, oldContent: "", newContent: String(a.content ?? "") },
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
      },
    };
  },
  finish: () => ({ icon: CircleCheckIcon, verb: "Finished" }),
};

export function toolView(ev: ActionEvent): ToolView {
  const render = TOOL_VIEWS[ev.tool_name];
  if (render) return render(ev.arguments ?? {});
  return { icon: FileIcon, verb: ev.tool_name || "Tool" };
}

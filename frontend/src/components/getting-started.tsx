"use client";

import { CheckmarkCircle02Icon, CircleIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";

import { useAuth } from "@/app/providers";
import { requestComposerFocus } from "@/lib/composer-selection";
import {
  useConversations,
  useMcpConnections,
  useSkills,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

type Step = {
  label: string;
  done: boolean;
  href?: string;
  onClick?: () => void;
};

export function GettingStarted() {
  const { auth, signIn } = useAuth();
  const { data: conversations } = useConversations();
  const { data: skills } = useSkills();
  const { data: mcp } = useMcpConnections();

  if (!conversations || !skills || !mcp) return null;

  const steps: Step[] = [
    {
      label: "Connect GitHub",
      done: !!auth?.github.connected,
      onClick: () => void signIn(),
    },
    {
      label: "Start your first chat",
      done: conversations.length > 0,
      href: "/",
      onClick: requestComposerFocus,
    },
    {
      label: "Add a skill or MCP server",
      done: skills.length > 0 || mcp.length > 0,
      href: "/customize",
    },
  ];
  const completed = steps.filter((s) => s.done).length;
  if (completed === steps.length) return null;

  return (
    <div className="mx-2 flex flex-col gap-2 rounded-lg border bg-sidebar-accent/40 p-3 group-data-[collapsible=icon]:hidden">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">Getting started</span>
        <span className="text-muted-foreground">
          {completed}/{steps.length}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${(completed / steps.length) * 100}%` }}
        />
      </div>
      <ol className="flex flex-col gap-0.5">
        {steps.map((step) => {
          const content = (
            <>
              <HugeiconsIcon
                icon={step.done ? CheckmarkCircle02Icon : CircleIcon}
                className={cn(
                  "size-3.5 shrink-0",
                  step.done ? "text-primary" : "text-muted-foreground",
                )}
              />
              <span className={cn(step.done && "text-muted-foreground line-through")}>
                {step.label}
              </span>
            </>
          );
          const className =
            "flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-xs hover:bg-sidebar-accent";
          return (
            <li key={step.label}>
              {step.done ? (
                <div className="flex items-center gap-2 px-1 py-1 text-xs">
                  {content}
                </div>
              ) : step.href ? (
                <Link href={step.href} onClick={step.onClick} className={className}>
                  {content}
                </Link>
              ) : (
                <button type="button" onClick={step.onClick} className={className}>
                  {content}
                </button>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

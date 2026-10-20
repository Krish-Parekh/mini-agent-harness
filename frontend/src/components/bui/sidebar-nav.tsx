"use client";

import type { ReactNode } from "react";

import { GlideMenu } from "@/components/bui/glide-menu";
import { cn } from "@/lib/utils";

export function SidebarNavGroup({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <GlideMenu
      highlightClassName="inset-x-2 rounded-[8px] bg-hover-2"
      className={cn("flex flex-col gap-px", className)}
    >
      {children}
    </GlideMenu>
  );
}

export function sidebarRowClass(active = false, className?: string) {
  return cn(
    "relative z-10 mx-2 flex h-8 min-w-0 items-center rounded-[8px] px-2 text-left text-ink-2 transition-[background-color,color,transform] hover:text-ink duration-150 active:scale-[0.98]",
    active && "bg-hover-2 text-ink group-hover/glide-menu:bg-transparent",
    className,
  );
}

export function SidebarNavIcon({ children }: { children: ReactNode }) {
  return (
    <span className="flex size-5 shrink-0 items-center justify-center [&_svg]:size-[18px]">
      {children}
    </span>
  );
}

export function SidebarNavText({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "ml-1.5 min-w-0 flex-1 truncate text-[14px] font-medium",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function SidebarNavLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mx-2 mb-1 flex h-8 items-center px-2 text-[12.5px] font-medium text-ink-3">
      {children}
    </div>
  );
}

export function SidebarNavSkeleton({ widths }: { widths: string[] }) {
  return (
    <div aria-hidden className="flex flex-col gap-px">
      {widths.map((w, i) => (
        <div key={i} className="mx-2 flex h-8 items-center gap-1.5 px-2">
          <span className="size-[18px] shrink-0 animate-pulse rounded-[5px] bg-hover-2" />
          <span
            className="h-3 animate-pulse rounded-full bg-hover-2"
            style={{ width: w }}
          />
        </div>
      ))}
    </div>
  );
}

"use client";

import { useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export function GlideMenu({
  children,
  className,
  highlightClassName = "inset-x-0 rounded-[8px] bg-hover",
  rowSelector = "[data-menu-row]",
}: {
  children: ReactNode;
  className?: string;
  highlightClassName?: string;
  rowSelector?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);
  const [visible, setVisible] = useState(false);

  const moveTo = (target: EventTarget | null) => {
    const container = ref.current;
    if (!(target instanceof Element) || !container) return;
    const row = target.closest(rowSelector);
    if (!(row instanceof HTMLElement) || !container.contains(row)) return;
    const top = row.getBoundingClientRect().top - container.getBoundingClientRect().top;
    const height = row.offsetHeight;
    setBox((prev) => (prev?.top === top && prev.height === height ? prev : { top, height }));
    setVisible(true);
  };

  return (
    <div
      ref={ref}
      onMouseOver={(event) => moveTo(event.target)}
      onMouseLeave={() => setVisible(false)}
      onFocusCapture={(event) => moveTo(event.target)}
      onBlurCapture={(event) => {
        if (!ref.current?.contains(event.relatedTarget as Node | null)) setVisible(false);
      }}
      className={cn("group/glide-menu relative", className)}
    >
      <span
        aria-hidden
        className={cn("pointer-events-none absolute", highlightClassName)}
        style={{
          transform: `translateY(${box?.top ?? 0}px)`,
          top: 0,
          height: box?.height ?? 0,
          opacity: box && visible ? 1 : 0,
          transition:
            "transform 220ms var(--ease-out-strong), height 220ms var(--ease-out-strong), opacity 150ms ease",
        }}
      />
      {children}
    </div>
  );
}

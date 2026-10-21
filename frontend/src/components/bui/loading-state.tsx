"use client";

import { useEffect, useState } from "react";

import { Shimmer } from "@/components/bui/shimmer";
import { useDelayedFlag } from "@/hooks/use-delayed-flag";
import { cn } from "@/lib/utils";

const CHEVRON = Array.from({ length: 9 }, (_, i) => {
  const r = Math.floor(i / 3);
  const c = i % 3;
  return (c + Math.abs(r - 1)) * 90;
});

export function PixelLoader({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("grid shrink-0 grid-cols-[repeat(3,4px)] gap-[1.5px]", className)}
    >
      {CHEVRON.map((delay, index) => (
        <span
          key={index}
          className="size-[4px] rounded-[1px] bg-ink opacity-15"
          style={{ animation: `pixel-on 650ms ease-in-out ${delay}ms infinite` }}
        />
      ))}
    </span>
  );
}

function formatElapsed(ds: number) {
  const total = ds / 10;
  if (total < 60) return `${total.toFixed(1)}s`;
  return `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="font-mono text-[12px] text-ink-3 tabular-nums">
      {formatElapsed(Math.max(0, Math.floor((now - since) / 100)))}
    </span>
  );
}

export function LoadingState({
  label,
  since,
  className,
}: {
  label: string;
  since?: number;
  className?: string;
}) {
  const visible = useDelayedFlag(true);
  if (!visible) return null;
  return (
    <div role="status" className={cn("flex w-fit items-center gap-2.5", className)}>
      <PixelLoader />
      <Shimmer duration={1.4} className="text-[13px] font-medium">
        {label}
      </Shimmer>
      {since !== undefined && <Elapsed since={since} />}
    </div>
  );
}

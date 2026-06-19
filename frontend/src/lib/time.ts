import { useEffect, useState } from "react";

// Final, precise duration for a completed step: "850ms", "2.3s", "2m 14s".
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSec = ms / 1000;
  if (totalSec < 60) return `${totalSec.toFixed(1)}s`;
  const mins = Math.floor(totalSec / 60);
  const secs = Math.round(totalSec % 60);
  return `${mins}m ${secs.toString().padStart(2, "0")}s`;
}

// Coarser, whole-second elapsed for a live ticking timer: "3s", "1m 02s".
export function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}m ${secs.toString().padStart(2, "0")}s`;
}

// "just now" / "5m ago" / "3d ago". Shared by the sidebar and chat.
export function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// Ticking elapsed milliseconds since `startMs`, updated every second while
// `active`. Events only arrive when a tool finishes, so a running step has no
// observation to read a duration from — this drives the live "Running 3s".
export function useElapsed(startMs: number | null, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || startMs == null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, startMs]);
  return startMs == null ? 0 : Math.max(0, now - startMs);
}

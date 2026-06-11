"use client";

import { ErrorFallback } from "@/components/error-fallback";

// Next 16.2: `unstable_retry` re-fetches and re-renders the segment (preferred
// over `reset`, which only re-renders). Catches render throws in the root
// segment's pages — not in app/layout.tsx (that's global-error.tsx's job), and
// not event-handler/async errors (those surface as toasts).
export default function RootError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return <ErrorFallback error={error} retry={unstable_retry} />;
}

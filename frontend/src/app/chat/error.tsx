"use client";

import { ErrorFallback } from "@/components/error-fallback";

// Unexpected render throws in the chat segment. The expected "conversation no
// longer exists" 404 is handled in-page via the stream's `missing` flag.
export default function ChatError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <ErrorFallback
      error={error}
      retry={unstable_retry}
      title="This chat hit an error"
    />
  );
}

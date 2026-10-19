"use client";

import { usePathname } from "next/navigation";

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
  const pathname = usePathname();
  const conversationId = pathname.startsWith("/chat/")
    ? pathname.slice("/chat/".length)
    : undefined;

  return (
    <ErrorFallback
      error={error}
      retry={unstable_retry}
      title="This chat hit an error"
      conversationId={conversationId}
    />
  );
}

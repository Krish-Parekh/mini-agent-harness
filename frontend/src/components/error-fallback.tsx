"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { HugeiconsIcon } from "@hugeicons/react";
import { Alert02Icon } from "@hugeicons/core-free-icons";

import { cn } from "@/lib/utils";

function FailureReference({
  conversationId,
  traceId,
  className,
}: {
  conversationId: string;
  traceId?: string | null;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const reference = traceId
    ? `conversation=${conversationId} trace=${traceId}`
    : `conversation=${conversationId}`;

  return (
    <div className={cn("space-y-1.5", className)}>
      <p className="text-xs text-muted-foreground">Reference</p>
      <code className="block break-all rounded-md bg-muted/60 p-2 text-xs">
        {reference}
      </code>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          navigator.clipboard
            .writeText(reference)
            .then(() => setCopied(true))
            .catch(() => setCopied(false));
        }}
      >
        {copied ? "Copied" : "Copy reference"}
      </Button>
      {!traceId && (
        <p className="text-xs text-muted-foreground">
          No trace recorded. Tracing was not configured for this run.
        </p>
      )}
    </div>
  );
}

export function ErrorFallback({
  error,
  retry,
  title = "Something went wrong",
  conversationId,
}: {
  error: Error & { digest?: string };
  retry: () => void;
  title?: string;
  conversationId?: string;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-full flex-1 items-center justify-center p-6">
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <HugeiconsIcon icon={Alert02Icon} />
          </EmptyMedia>
          <EmptyTitle>{title}</EmptyTitle>
          <EmptyDescription>
            {process.env.NODE_ENV === "development"
              ? error.message
              : "An unexpected error occurred. Your work is safe. Try again."}
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="gap-4">
          {(conversationId || error.digest) && (
            <FailureReference
              conversationId={conversationId ?? "none"}
              traceId={error.digest}
              className="text-left"
            />
          )}
          <Button onClick={retry}>Try again</Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}

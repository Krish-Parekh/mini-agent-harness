"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api, ApiError, type ChangedFile, type ChangeSide } from "@/lib/api";
import type { PreviewKind } from "@/lib/preview";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/bui/loading-state";

type Loaded = { url: string } | { error: string };

const RENDER: Record<PreviewKind, (url: string, name: string) => ReactNode> = {
  image: (url, name) => (
    <Image
      src={url}
      alt={name}
      width={1024}
      height={1024}
      unoptimized
      className="h-auto w-auto max-w-full rounded-control shadow-hairline"
    />
  ),
  audio: (url) => <audio controls src={url} className="w-full" />,
  video: (url) => (
    <video controls src={url} className="max-h-[70vh] w-full rounded-control bg-field" />
  ),
  pdf: (url, name) => (
    <iframe src={url} title={name} className="h-[75vh] w-full rounded-control shadow-hairline" />
  ),
};

export function MediaPreview({
  kind,
  conversationId,
  path,
  revision,
  scope,
  side,
}: {
  kind: PreviewKind;
  conversationId: string;
  path: string;
  revision: number;
  scope?: string;
  side?: ChangeSide;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    let active = true;
    let url: string | null = null;
    const blob =
      scope && side
        ? api.changeBlob(conversationId, path, scope, side)
        : api.fileBlob(conversationId, path);
    blob
      .then((b) => {
        if (!active) return;
        url = URL.createObjectURL(b);
        setLoaded({ url });
      })
      .catch(
        (e) =>
          active &&
          setLoaded({
            error:
              e instanceof ApiError && e.status === 413 ? e.detail : "Couldn't load this file.",
          }),
      );
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [conversationId, path, revision, scope, side]);

  if (loaded === null) return <LoadingState label="Loading preview" className="py-2" />;
  if ("error" in loaded) return <p className="text-[12.5px] text-ink-3">{loaded.error}</p>;
  return RENDER[kind](loaded.url, path);
}

const SIDES: Record<ChangedFile["status"], ChangeSide[]> = {
  added: ["after"],
  deleted: ["before"],
  modified: ["before", "after"],
};

export function MediaChange({
  kind,
  conversationId,
  path,
  status,
  scope,
  revision,
}: {
  kind: PreviewKind;
  conversationId: string;
  path: string;
  status: ChangedFile["status"];
  scope: string;
  revision: number;
}) {
  const sides = SIDES[status];
  return (
    <div className={cn("grid gap-3 p-3", kind === "image" && sides.length > 1 && "grid-cols-2")}>
      {sides.map((side) => (
        <figure key={side} className="flex min-w-0 flex-col items-start gap-1.5">
          {sides.length > 1 && (
            <figcaption className="text-[11.5px] text-ink-3">
              {side === "before" ? "Before" : "After"}
            </figcaption>
          )}
          <MediaPreview
            kind={kind}
            conversationId={conversationId}
            path={path}
            revision={revision}
            scope={scope}
            side={side}
          />
        </figure>
      ))}
    </div>
  );
}

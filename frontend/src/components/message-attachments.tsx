"use client";

import { DownloadIcon, PaperclipIcon } from "lucide-react";
import Image from "next/image";

import type { AttachmentRef } from "@/lib/api";
import { useAttachmentUrl } from "@/lib/queries";

function AttachmentItem({ attachment }: { attachment: AttachmentRef }) {
  const { data: url } = useAttachmentUrl(attachment);

  if (attachment.kind === "image") {
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer" className="block">
        <Image
          src={url}
          alt={attachment.name}
          width={160}
          height={160}
          unoptimized
          className="h-28 w-auto max-w-60 rounded-control object-cover shadow-hairline"
        />
      </a>
    ) : (
      <div className="h-28 w-28 animate-pulse rounded-control bg-line" />
    );
  }

  return (
    <a
      href={url}
      download={attachment.name}
      aria-disabled={!url}
      className="flex h-7 max-w-60 items-center gap-1.5 rounded-chip bg-surface px-2 text-[12px] text-ink-2 shadow-hairline transition-colors duration-100 hover:text-ink aria-disabled:pointer-events-none aria-disabled:opacity-60"
    >
      <PaperclipIcon className="size-3 shrink-0 text-ink-3" />
      <span className="truncate">{attachment.name}</span>
      <DownloadIcon className="size-3 shrink-0 text-ink-3" />
    </a>
  );
}

export function MessageAttachments({ attachments }: { attachments: AttachmentRef[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-2 whitespace-normal">
      {attachments.map((attachment) => (
        <AttachmentItem key={attachment.path} attachment={attachment} />
      ))}
    </div>
  );
}

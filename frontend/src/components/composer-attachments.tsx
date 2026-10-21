"use client";

import { PaperclipIcon } from "lucide-react";
import Image from "next/image";
import {
  type ClipboardEvent,
  type DragEvent,
  type ReactNode,
  useCallback,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import {
  PromptBarButton,
  PromptBarChip,
  PromptBarHeader,
} from "@/components/bui/prompt-bar";
import type { AttachmentRef } from "@/lib/api";
import {
  type DraftAttachment,
  MAX_ATTACHMENTS,
  prepareAttachment,
  uploadAttachments,
} from "@/lib/attachments";

export function useComposerAttachments() {
  const [items, setItems] = useState<DraftAttachment[]>([]);
  const [uploading, setUploading] = useState(false);

  async function add(files: FileList) {
    const list = Array.from(files);
    if (items.length + list.length > MAX_ATTACHMENTS) {
      toast.error(`Up to ${MAX_ATTACHMENTS} attachments per message.`);
      return;
    }
    const results = await Promise.allSettled(list.map(prepareAttachment));
    const ready: DraftAttachment[] = [];
    for (const result of results) {
      if (result.status === "fulfilled") ready.push(result.value);
      else toast.error((result.reason as Error).message);
    }
    setItems((current) => [...current, ...ready].slice(0, MAX_ATTACHMENTS));
  }

  const restore = useCallback((refs: AttachmentRef[]) => {
    setItems(
      refs.map((ref) => ({ id: crypto.randomUUID(), name: ref.name, source: ref, kind: ref.kind })),
    );
  }, []);

  function remove(id: string) {
    const item = items.find((i) => i.id === id);
    if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl);
    setItems(items.filter((i) => i.id !== id));
  }

  function clear() {
    for (const item of items) if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    setItems([]);
  }

  async function upload(): Promise<AttachmentRef[] | null> {
    setUploading(true);
    try {
      return await uploadAttachments(items);
    } catch (e) {
      toast.error((e as Error).message);
      return null;
    } finally {
      setUploading(false);
    }
  }

  return { items, uploading, add, restore, remove, clear, upload };
}

type ComposerAttachments = ReturnType<typeof useComposerAttachments>;

export function AttachmentDropZone({
  attachments,
  children,
}: {
  attachments: ComposerAttachments;
  children: ReactNode;
}) {
  function onDragOver(event: DragEvent<HTMLDivElement>) {
    if (event.dataTransfer.types.includes("Files")) event.preventDefault();
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    if (event.dataTransfer.files.length === 0) return;
    event.preventDefault();
    void attachments.add(event.dataTransfer.files);
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    if (event.clipboardData.files.length === 0) return;
    event.preventDefault();
    void attachments.add(event.clipboardData.files);
  }

  return (
    <div onDragOver={onDragOver} onDrop={onDrop} onPaste={onPaste}>
      {children}
    </div>
  );
}

export function AttachmentChips({ attachments }: { attachments: ComposerAttachments }) {
  if (attachments.items.length === 0) return null;
  return (
    <PromptBarHeader>
      {attachments.items.map((item) => (
        <PromptBarChip
          key={item.id}
          icon={
            item.previewUrl ? (
              <Image
                src={item.previewUrl}
                alt=""
                width={16}
                height={16}
                unoptimized
                className="size-4 rounded-[3px] object-cover"
              />
            ) : (
              <PaperclipIcon className="size-3 text-ink-3" />
            )
          }
          label={item.name}
          removeLabel={`Remove ${item.name}`}
          onRemove={() => attachments.remove(item.id)}
        />
      ))}
    </PromptBarHeader>
  );
}

export function AttachButton({
  attachments,
  disabled,
}: {
  attachments: ComposerAttachments;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <PromptBarButton
        aria-label="Attach files"
        disabled={disabled}
        onClick={() => input.current?.click()}
      >
        <PaperclipIcon className="size-3.5" />
      </PromptBarButton>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          if (event.target.files) void attachments.add(event.target.files);
          event.target.value = "";
        }}
      />
    </>
  );
}

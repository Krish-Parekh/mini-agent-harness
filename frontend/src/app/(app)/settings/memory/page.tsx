"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BrainIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Pill } from "@/components/bui/button";
import { LoadingState } from "@/components/bui/loading-state";
import { ValuePill } from "@/components/bui/value-pill";
import { SettingsPage } from "@/components/settings/settings-ui";
import { Textarea } from "@/components/ui/textarea";
import { api, type Memory } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { queryKeys, useMemories } from "@/lib/queries";

const ABOUT_YOU = "About you";

function groupByScope(memories: Memory[]) {
  const groups = new Map<string, Memory[]>();
  for (const memory of memories) {
    const key = memory.repo ?? ABOUT_YOU;
    groups.set(key, [...(groups.get(key) ?? []), memory]);
  }
  return [...groups.entries()].sort(([a], [b]) =>
    a === ABOUT_YOU ? -1 : b === ABOUT_YOU ? 1 : a.localeCompare(b),
  );
}

function MemoryRow({ memory }: { memory: Memory }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.memories });

  const save = useMutation({
    mutationFn: (content: string) => api.updateMemory(memory.id, content),
    onSuccess: () => {
      setDraft(null);
      invalidate();
    },
    onError: (e) => toast.error(messageFor(e)),
  });

  const remove = useMutation({
    mutationFn: () => api.deleteMemory(memory.id),
    onSuccess: invalidate,
    onError: (e) => toast.error(messageFor(e)),
  });

  const summary = memory.content.split("\n").find((line) => line.trim()) ?? "";

  return (
    <div className="flex flex-col gap-2 rounded-control px-2.5 py-2">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate font-mono text-[12.5px] text-ink">{memory.path}</span>
          {draft === null && (
            <p className="truncate text-[12.5px] text-ink-2">{summary}</p>
          )}
        </div>
        {draft === null && (
          <div className="flex shrink-0 gap-1">
            <Pill variant="ghost" size="xs" onClick={() => setDraft(memory.content)}>
              Edit
            </Pill>
            <Pill
              variant="ghost"
              size="xs"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Delete
            </Pill>
          </div>
        )}
      </div>
      {draft !== null && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) save.mutate(draft);
          }}
        >
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="font-mono text-[12.5px]"
            autoFocus
          />
          <div className="flex justify-end gap-1">
            <Pill type="button" variant="ghost" size="xs" onClick={() => setDraft(null)}>
              Cancel
            </Pill>
            <Pill
              type="submit"
              variant="primary"
              size="xs"
              disabled={save.isPending || !draft.trim()}
            >
              Save
            </Pill>
          </div>
        </form>
      )}
    </div>
  );
}

export default function MemorySettingsPage() {
  const { data: memories, isPending } = useMemories();

  return (
    <SettingsPage title="Memory">
      <p className="-mt-5 text-[13px] text-ink-3">
        Notes the agent saved to carry into future chats. Notes about you apply in every
        project; project notes apply only to that project.
      </p>

      {isPending ? (
        <LoadingState label="Loading memory" />
      ) : !memories?.length ? (
        <div className="flex flex-col items-center gap-2 rounded-card bg-surface px-6 py-10 text-center shadow-card">
          <span className="flex size-8 items-center justify-center rounded-full bg-brand-tint text-brand">
            <BrainIcon className="size-4" />
          </span>
          <p className="text-[14px] font-medium text-ink">No memories yet</p>
          <p className="max-w-sm text-[13px] text-ink-3">
            Tell the agent a preference or correction in any chat, like &quot;always run the
            linter before finishing&quot;, and it saves a note here.
          </p>
        </div>
      ) : (
        groupByScope(memories).map(([scope, list]) => (
          <section key={scope} className="flex flex-col gap-2">
            <div className="flex items-center gap-2 px-1">
              <h2
                className={
                  scope === ABOUT_YOU
                    ? "text-[13px] text-ink-2"
                    : "font-mono text-[12.5px] text-ink-2"
                }
              >
                {scope}
              </h2>
              <ValuePill>{list.length}</ValuePill>
            </div>
            <div className="flex flex-col rounded-card bg-surface p-1 shadow-card">
              {list.map((memory) => (
                <MemoryRow key={memory.id} memory={memory} />
              ))}
            </div>
          </section>
        ))
      )}
    </SettingsPage>
  );
}

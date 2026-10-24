"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon } from "lucide-react";

import { useConversationStream } from "@/hooks/use-conversation-stream";
import { buildWorkers } from "@/lib/workers";
import { ConversationTimeline } from "@/components/conversation-stream";
import { ChangesPanel } from "@/components/changes-panel";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/bui/conversation";
import { LoadingState } from "@/components/bui/loading-state";
import { ScrollablePreview } from "@/lib/tool-views";
import { TaskBadge } from "@/components/bui/task-rows";
import { ValuePill } from "@/components/bui/value-pill";
import {
  WORKER_CONVERSATION_STATUS,
  WORKER_STATUS,
  WORKER_TONE,
  useWorkerDuration,
  workerObservations,
  workerOutcome,
} from "@/components/workers";
import { SidebarTrigger } from "@/components/ui/sidebar";
import type { WorkerView } from "@/lib/workers";

const noop = () => {};

export default function WorkerPage({
  params,
}: {
  params: Promise<{ id: string; workerId: string }>;
}) {
  const { id, workerId } = use(params);
  const { conversation, missing, connected, events, changes, refreshChanges, changesRevision, prStep } =
    useConversationStream(id);
  const worker = useMemo(
    () =>
      Array.from(buildWorkers(events).values())
        .flat()
        .find((w) => w.worker_id === workerId),
    [events, workerId],
  );

  if (missing || (connected && !worker)) {
    return (
      <div className="flex h-full flex-1 flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm font-medium">This worker is not in the conversation.</p>
        <Link href={`/chat/${id}`} className="text-sm text-muted-foreground underline">
          Back to the chat
        </Link>
      </div>
    );
  }
  if (!worker) {
    return (
      <div className="flex h-full flex-1 items-center justify-center">
        <LoadingState label="Loading worker" />
      </div>
    );
  }
  return (
    <WorkerChat
      id={id}
      worker={worker}
      parentTitle={conversation?.title ?? conversation?.repo ?? "Chat"}
      changes={changes}
      prNumber={conversation?.pr_number ?? null}
      prUrl={conversation?.pr_url ?? null}
      onSynced={refreshChanges}
      revision={changesRevision}
      prStep={prStep}
    />
  );
}

function WorkerChat({
  id,
  worker,
  parentTitle,
  changes,
  prNumber,
  prUrl,
  onSynced,
  revision,
  prStep,
}: {
  id: string;
  worker: WorkerView;
  parentTitle: string;
  changes: Parameters<typeof ChangesPanel>[0]["changes"];
  prNumber: number | null;
  prUrl: string | null;
  onSynced: () => void;
  revision: number;
  prStep: Parameters<typeof ChangesPanel>[0]["prStep"];
}) {
  const duration = useWorkerDuration(worker);
  const observationByCall = useMemo(() => workerObservations(worker), [worker]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [scope, setScope] = useState(worker.worker_id);
  const [panelOpen, setPanelOpen] = useState(true);
  const running = worker.status === "running";
  const outcome = running ? null : workerOutcome(worker);
  const hasChanges = worker.branch !== null;

  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="relative z-10 flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
          <SidebarTrigger />
          <Link
            href={`/chat/${id}`}
            className="flex min-w-0 shrink items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeftIcon className="size-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{parentTitle}</span>
          </Link>
          <span className="text-muted-foreground" aria-hidden="true">
            /
          </span>
          <TaskBadge compact status={WORKER_STATUS[worker.status]} />
          <span className="min-w-0 truncate text-sm font-medium">{worker.title}</span>
          <ValuePill tone={WORKER_TONE[worker.worker_kind]} className="shrink-0">
            {worker.worker_kind}
          </ValuePill>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
            {duration}
          </span>
        </header>
        <div className="mx-auto flex w-full min-h-0 max-w-3xl flex-1 flex-col px-4 py-2">
          <Conversation>
            <ConversationContent className="space-y-6 px-0 py-0">
              <ConversationTimeline
                events={worker.events}
                observationByCall={observationByCall}
                status={WORKER_CONVERSATION_STATUS[worker.status]}
                onApprove={noop}
                onReject={noop}
                onSelectFile={
                  hasChanges
                    ? (path) => {
                        setSelectedPath(path);
                        setScope(worker.worker_id);
                        setPanelOpen(true);
                      }
                    : undefined
                }
              />
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>
          <footer className="mt-3 flex flex-col gap-2 rounded-card bg-surface px-3 py-2.5 text-[12.5px] text-ink-2 shadow-hairline">
            <p className="text-pretty">
              {running
                ? "This worker is running on its own. It reports back to the main chat when it finishes."
                : (outcome ?? "This worker has ended.")}{" "}
              <Link href={`/chat/${id}`} className="text-ink underline">
                Back to the main chat
              </Link>
            </p>
            {worker.conflict && (
              <ScrollablePreview>
                <pre className="whitespace-pre-wrap break-words rounded-control bg-red-tint px-2.5 py-2 font-mono text-[11.5px] leading-[1.6] text-red">
                  {worker.conflict}
                </pre>
              </ScrollablePreview>
            )}
          </footer>
        </div>
      </div>
      {hasChanges && panelOpen && (
        <ChangesPanel
          conversationId={id}
          changes={changes}
          prNumber={prNumber}
          prUrl={prUrl}
          running={running}
          selectedPath={selectedPath}
          onSelectPath={setSelectedPath}
          scope={scope}
          onScopeChange={setScope}
          workers={[{ id: worker.worker_id, title: worker.title }]}
          onClose={() => setPanelOpen(false)}
          onSynced={onSynced}
          revision={revision}
          prStep={prStep}
        />
      )}
    </div>
  );
}

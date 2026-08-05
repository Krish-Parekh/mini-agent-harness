"use client";

import { use, useRef, useState } from "react";
import { toast } from "sonner";

import Link from "next/link";

import { api, type ConversationStatus } from "@/lib/api";
import { sendMessage } from "@/lib/collections";
import { messageFor } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { useConversationStream } from "@/hooks/use-conversation-stream";
import { ConversationTimeline } from "@/components/conversation-stream";
import { ChangesPanel } from "@/components/changes-panel";
import { QuestionCard, type Question } from "@/components/question-card";
import { HugeiconsIcon } from "@hugeicons/react";
import { PanelRightIcon } from "@hugeicons/core-free-icons";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
  ConversationScrollAnchor,
} from "@/components/ai-elements/conversation";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import { AlertTriangleIcon, CheckIcon } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";

// First entry is the default and matches the backend config default.
const MODELS = [
  { id: "gpt-4o-mini", name: "GPT-4o mini" },
  { id: "gpt-4o", name: "GPT-4o" },
  { id: "gpt-4.1", name: "GPT-4.1" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 mini" },
];

const STATUS_STYLES: Record<ConversationStatus, string> = {
  idle: "bg-muted text-muted-foreground",
  running: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  waiting_for_confirmation: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  finished: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  stuck: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  error: "bg-destructive/10 text-destructive",
};

const STATUS_LABELS: Record<ConversationStatus, string> = {
  idle: "Idle",
  running: "Running",
  waiting_for_confirmation: "Waiting for you",
  finished: "Finished",
  stuck: "Stuck",
  error: "Error",
};

function StatusChip({ status }: { status: ConversationStatus }) {
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        STATUS_STYLES[status],
      )}
    >
      {status === "running" ? (
        <Spinner className="size-3" />
      ) : (
        <span className="size-1.5 rounded-full bg-current" />
      )}
      {STATUS_LABELS[status]}
    </span>
  );
}

export default function ChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  // The hook owns everything derivable from the live event stream + status;
  // the page keeps only input/presentation state.
  const {
    conversation,
    exists,
    missing,
    connected,
    events,
    status,
    setStatus,
    busy,
    waiting,
    changes,
    refreshChanges,
    observationByCall,
    lastUnresolvedAction,
    pendingQuestion,
    pendingPlan,
    livePlan,
    lastUserTurnId,
    stop: stopRun,
  } = useConversationStream(id);

  const [input, setInput] = useState("");
  const [model, setModel] = useState(MODELS[0].id);
  const [modelOpen, setModelOpen] = useState(false);
  const [dismissedQuestionId, setDismissedQuestionId] = useState<string | null>(
    null,
  );
  const selectedModel = MODELS.find((m) => m.id === model);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const lastSentText = useRef("");

  const showQuestion =
    !!pendingQuestion &&
    pendingQuestion.id !== dismissedQuestionId &&
    status !== "running";

  const showBuild = !!pendingPlan && status !== "running";

  function openFile(path: string) {
    setSelectedPath(path);
    setPanelOpen(true);
  }

  // Optimistically flip to "running" for instant feedback, but restore the
  // prior status (and surface the error) if the request fails — otherwise a
  // rejected confirm/approve would leave the composer locked on "running".
  function optimisticRun(fn: () => Promise<unknown>) {
    const prev = status;
    setStatus("running");
    fn().catch((e) => {
      setStatus(prev);
      toast.error(messageFor(e));
    });
  }

  async function submit(text: string, restoreInput: boolean) {
    lastSentText.current = text;
    const prev = status;
    setStatus("running");
    try {
      await sendMessage({
        conversationId: id,
        clientEventId: crypto.randomUUID(),
        text,
        model,
      }).isPersisted.promise;
    } catch (e) {
      if (restoreInput) setInput(text);
      setStatus(prev);
      toast.error(messageFor(e));
    }
  }

  async function sendAnswer(text: string) {
    if (busy) return;
    await submit(text, false);
  }

  function stop() {
    if (!busy) return;
    // Restore the prompt right away; the turn is trimmed once status settles.
    if (lastSentText.current) setInput(lastSentText.current);
    stopRun();
  }

  async function send(message: PromptInputMessage) {
    const text = message.text.trim();
    if (!text || busy) return;
    setInput("");
    await submit(text, true);
  }

  if (missing) {
    return (
      <div className="flex h-full flex-1 flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm font-medium">This conversation no longer exists.</p>
        <Link href="/" className="text-sm text-muted-foreground underline">
          Back to home
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="relative z-10 flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-background px-4">
          <div className="flex min-w-0 items-center gap-2">
            <SidebarTrigger />
            {conversation?.repo && (
              <span className="truncate text-sm font-medium">
                {conversation.repo}
              </span>
            )}
            {exists && <StatusChip status={status} />}
            {exists && !connected && (
              <span className="flex items-center gap-1.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                <Spinner className="size-3" />
                Reconnecting…
              </span>
            )}
          </div>
          {!panelOpen && (
            <button
              type="button"
              onClick={() => setPanelOpen(true)}
              aria-label="Show files panel"
              className="rounded p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            >
              <HugeiconsIcon icon={PanelRightIcon} className="size-4" />
            </button>
          )}

          {panelOpen && (
            <button
            type="button"
            onClick={() => setPanelOpen(false)}
            aria-label="Hide files panel"
            className="rounded p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          >
            <HugeiconsIcon icon={PanelRightIcon} className="size-4" />
          </button>
          )}
        </header>
        <div className="mx-auto flex w-full min-h-0 max-w-3xl flex-1 flex-col px-4 py-2">
          <Conversation>
            <ConversationContent className="space-y-6 px-0 py-0">
              <ConversationTimeline
                events={events}
                observationByCall={observationByCall}
                status={status}
                pendingId={waiting ? lastUnresolvedAction?.id : undefined}
                pendingQuestionId={showQuestion ? pendingQuestion?.id : undefined}
                pendingPlanId={showBuild ? pendingPlan?.id : undefined}
                livePlan={livePlan}
                onBuild={() => optimisticRun(() => api.approvePlan(id))}
                onApprove={() => optimisticRun(() => api.confirm(id, true))}
                onReject={() => optimisticRun(() => api.confirm(id, false))}
                onSelectFile={openFile}
              />
              <ConversationScrollAnchor turnKey={lastUserTurnId} />
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>

          {showQuestion && pendingQuestion && (
            <div className="mt-3">
              <QuestionCard
                key={pendingQuestion.id}
                questions={
                  (pendingQuestion.arguments?.questions as Question[]) ?? []
                }
                onSubmit={sendAnswer}
                onDismiss={() => setDismissedQuestionId(pendingQuestion.id)}
              />
            </div>
          )}

          {status === "error" && (
            <div
              role="alert"
              className="mt-3 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
              <span>
                The agent hit an error. Edit your message and resend, or check
                the details above.
              </span>
            </div>
          )}

          {status === "stuck" && (
            <div
              role="status"
              className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-100"
            >
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
              <span>
                The agent got stuck in a loop. Send a new message to nudge it
                in a different direction, or review the steps above.
              </span>
            </div>
          )}

          <PromptInput onSubmit={send} className="mt-3">
        <PromptInputBody>
          <PromptInputTextarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              waiting
                ? "Approve or reject the action above…"
                : showQuestion
                  ? "Or reply directly…"
                  : "Send a message…"
            }
            disabled={busy}
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <ModelSelector open={modelOpen} onOpenChange={setModelOpen}>
              <ModelSelectorTrigger
                render={
                  <PromptInputButton>
                    <ModelSelectorLogo provider="openai" />
                    <ModelSelectorName>
                      {selectedModel?.name ?? "Model"}
                    </ModelSelectorName>
                  </PromptInputButton>
                }
              />
              <ModelSelectorContent className="[&_[data-slot=dialog-close]]:top-2.5 [&_[data-slot=dialog-close]]:right-2.5 [&_[data-slot=command-input-wrapper]]:pr-12">
                <ModelSelectorInput placeholder="Search models…" />
                <ModelSelectorList>
                  <ModelSelectorEmpty>No models found.</ModelSelectorEmpty>
                  <ModelSelectorGroup heading="OpenAI">
                    {MODELS.map((m) => (
                      <ModelSelectorItem
                        key={m.id}
                        value={m.id}
                        onSelect={() => {
                          setModel(m.id);
                          setModelOpen(false);
                        }}
                      >
                        <ModelSelectorLogo provider="openai" />
                        <ModelSelectorName>{m.name}</ModelSelectorName>
                        {model === m.id ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </ModelSelectorItem>
                    ))}
                  </ModelSelectorGroup>
                </ModelSelectorList>
              </ModelSelectorContent>
            </ModelSelector>
          </PromptInputTools>
          <PromptInputSubmit
            status={busy ? "streaming" : status === "error" ? "error" : undefined}
            onStop={stop}
            disabled={!busy && !input.trim()}
          />
        </PromptInputFooter>
        </PromptInput>
        </div>
      </div>

      {panelOpen && (
        <ChangesPanel
          conversationId={id}
          changes={changes}
          prNumber={conversation?.pr_number ?? null}
          prUrl={conversation?.pr_url ?? null}
          running={status === "running"}
          selectedPath={selectedPath}
          onSelectPath={setSelectedPath}
          onClose={() => setPanelOpen(false)}
          onSynced={refreshChanges}
        />
      )}
    </div>
  );
}

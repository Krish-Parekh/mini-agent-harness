"use client";

import { useQueryClient } from "@tanstack/react-query";
import { use, useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import Link from "next/link";

import { api, type Skill } from "@/lib/api";
import { sendMessage } from "@/lib/collections";
import { messageFor } from "@/lib/errors";
import { useConversationContext } from "@/lib/queries";
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
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { DEFAULT_MODEL, ModelPicker } from "@/components/model-picker";
import { SkillChips, SkillSlashTextarea } from "@/components/skill-slash-menu";
import { AlertTriangleIcon } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";

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
  const [model, setModel] = useState<string | null>(null);
  const { data: context } = useConversationContext(id, exists);
  const [sessionSkills, setSessionSkills] = useState<Skill[]>([]);
  const [skillsFor, setSkillsFor] = useState(id);
  if (skillsFor !== id) {
    setSkillsFor(id);
    setSessionSkills([]);
    setModel(null);
  }
  const queryClient = useQueryClient();
  const [dismissedQuestionId, setDismissedQuestionId] = useState<string | null>(
    null,
  );
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const lastSentText = useRef("");

  const showQuestion =
    !!pendingQuestion &&
    pendingQuestion.id !== dismissedQuestionId &&
    status !== "running";

  const showBuild = !!pendingPlan && status !== "running";

  const openFile = useCallback((path: string) => {
    setSelectedPath(path);
    setPanelOpen(true);
  }, []);
  const closePanel = useCallback(() => setPanelOpen(false), []);

  // Optimistically flip to "running" for instant feedback, but restore the
  // prior status (and surface the error) if the request fails. Otherwise a
  // rejected confirm/approve would leave the composer locked on "running".
  const optimisticRun = useCallback(
    (fn: () => Promise<unknown>) => {
      const prev = status;
      setStatus("running");
      fn().catch((e) => {
        setStatus(prev);
        toast.error(messageFor(e));
      });
    },
    [status, setStatus],
  );
  const approvePlan = useCallback(
    () => optimisticRun(() => api.approvePlan(id)),
    [optimisticRun, id],
  );
  const approveAction = useCallback(
    () => optimisticRun(() => api.confirm(id, true)),
    [optimisticRun, id],
  );
  const rejectAction = useCallback(
    () => optimisticRun(() => api.confirm(id, false)),
    [optimisticRun, id],
  );

  async function submit(text: string, restoreInput: boolean) {
    lastSentText.current = text;
    const prev = status;
    setStatus("running");
    try {
      await sendMessage({
        conversationId: id,
        clientEventId: crypto.randomUUID(),
        text,
        model: model ?? undefined,
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

  async function toggleSkill(skill: Skill, enabled: boolean) {
    try {
      await api.setConversationSkill(id, skill.id, enabled);
      setSessionSkills((prev) =>
        enabled ? [...prev, skill] : prev.filter((s) => s.id !== skill.id),
      );
      queryClient.invalidateQueries({ queryKey: ["conversation-skills", id] });
      toast.success(
        enabled ? `Enabled “${skill.name}”` : `Disabled “${skill.name}”`,
      );
    } catch (e) {
      toast.error(messageFor(e));
    }
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
                onBuild={approvePlan}
                onApprove={approveAction}
                onReject={rejectAction}
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
            <SkillChips
              skills={sessionSkills}
              onRemove={(skill) => void toggleSkill(skill, false)}
            />
            <PromptInputBody>
              <SkillSlashTextarea
                value={input}
                onValueChange={setInput}
                excludeIds={sessionSkills.map((s) => s.id)}
                onPickSkill={(skill) => void toggleSkill(skill, true)}
                placeholder={
                  waiting
                    ? "Approve or reject the action above…"
                    : showQuestion
                      ? "Or reply directly…"
                      : "Send a message, / for skills…"
                }
                disabled={busy}
              />
            </PromptInputBody>
            <PromptInputFooter>
              <PromptInputTools>
                <ModelPicker
                  value={model ?? context?.model ?? DEFAULT_MODEL}
                  onChange={setModel}
                />
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
          onClose={closePanel}
          onSynced={refreshChanges}
        />
      )}
    </div>
  );
}

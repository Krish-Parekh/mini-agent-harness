"use client";

import { useQueryClient } from "@tanstack/react-query";
import { use, useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import Link from "next/link";

import { api, type AttachmentRef } from "@/lib/api";
import { sendMessage } from "@/lib/collections";
import { messageFor } from "@/lib/errors";
import { queryKeys, useConversationContext, useTurns } from "@/lib/queries";
import { useConversationStream } from "@/hooks/use-conversation-stream";
import { ConversationTimeline } from "@/components/conversation-stream";
import { ChangesPanel } from "@/components/changes-panel";
import { QuestionCard, type Question } from "@/components/question-card";
import {
  type ProposedSkill,
  SKIPPED_SKILLS_MESSAGE,
  includedSkillsMessage,
} from "@/components/bui/skill-proposal-card";
import { HugeiconsIcon } from "@hugeicons/react";
import { PanelRightIcon } from "@hugeicons/core-free-icons";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
  ConversationScrollAnchor,
} from "@/components/bui/conversation";
import {
  PromptBar,
  PromptBarFooter,
  PromptBarSubmit,
  PromptBarTools,
  type PromptBarMessage,
} from "@/components/bui/prompt-bar";
import {
  AttachButton,
  AttachmentChips,
  AttachmentDropZone,
  useComposerAttachments,
} from "@/components/composer-attachments";
import { DEFAULT_MODEL, ModelPicker } from "@/components/model-picker";
import { SkillSlashTextarea } from "@/components/skill-slash-menu";
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
    changesRevision,
    observationByCall,
    lastUnresolvedAction,
    pendingQuestion,
    pendingSkillProposal,
    pendingPlan,
    livePlan,
    lastUserTurnId,
    stop: stopRun,
    prStep,
  } = useConversationStream(id);
  const { data: turns } = useTurns(id, status);
  const rewindable = useMemo(() => new Set(turns?.map((t) => t.id)), [turns]);

  const [input, setInput] = useState("");
  const attachments = useComposerAttachments();
  const [model, setModel] = useState<string | null>(null);
  const { data: context } = useConversationContext(id, exists);
  const [modelFor, setModelFor] = useState(id);
  if (modelFor !== id) {
    setModelFor(id);
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

  const showSkills = !!pendingSkillProposal && status !== "running";

  const repo = conversation?.repo ?? null;

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
  const pendingCallId = lastUnresolvedAction?.tool_call_id;
  const approveAction = useCallback(() => {
    if (pendingCallId) optimisticRun(() => api.confirm(id, pendingCallId, true));
  }, [optimisticRun, id, pendingCallId]);
  const rejectAction = useCallback(() => {
    if (pendingCallId) optimisticRun(() => api.confirm(id, pendingCallId, false));
  }, [optimisticRun, id, pendingCallId]);

  const submit = useCallback(
    async (text: string, restoreInput: boolean, attachments: AttachmentRef[] = []) => {
      lastSentText.current = text;
      const prev = status;
      setStatus("running");
      try {
        await sendMessage({
          conversationId: id,
          clientEventId: crypto.randomUUID(),
          text,
          model: model ?? undefined,
          attachments,
        }).isPersisted.promise;
        return true;
      } catch (e) {
        if (restoreInput) setInput(text);
        setStatus(prev);
        toast.error(messageFor(e));
        return false;
      }
    },
    [id, model, status, setStatus, setInput],
  );

  const restoreAttachments = attachments.restore;
  const rewindTo = useCallback(
    async (messageId: string) => {
      try {
        const result = await api.rewind(id, messageId);
        setInput(result.text);
        restoreAttachments(result.attachments);
        refreshChanges();
        void queryClient.invalidateQueries({ queryKey: queryKeys.turns(id) });
      } catch (e) {
        toast.error(messageFor(e));
      }
    },
    [id, setInput, restoreAttachments, refreshChanges, queryClient],
  );

  const installSkill = useCallback(
    (skill: ProposedSkill) => {
      if (!repo) return Promise.reject(new Error("This chat has no repository."));
      return api.installSkill({
        source: skill.source,
        skill_id: skill.skill_id,
        repo,
      });
    },
    [repo],
  );
  const includeSkills = useCallback(
    (names: string[]) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills });
      if (!busy) void submit(includedSkillsMessage(names), false);
    },
    [queryClient, busy, submit],
  );
  const skipSkills = useCallback(() => {
    if (!busy) void submit(SKIPPED_SKILLS_MESSAGE, false);
  }, [busy, submit]);

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

  async function send(message: PromptBarMessage) {
    const text = message.text.trim();
    if ((!text && attachments.items.length === 0) || busy || attachments.uploading) return;
    const uploaded = await attachments.upload();
    if (!uploaded) return;
    setInput("");
    if (await submit(text, true, uploaded)) attachments.clear();
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
                pendingSkillsId={showSkills ? pendingSkillProposal?.id : undefined}
                repo={repo}
                livePlan={livePlan}
                onBuild={approvePlan}
                onApprove={approveAction}
                onReject={rejectAction}
                onSelectFile={openFile}
                onInstallSkill={installSkill}
                onIncludeSkills={includeSkills}
                onSkipSkills={skipSkills}
                onRewind={rewindTo}
                rewindable={rewindable}
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

          <AttachmentDropZone attachments={attachments}>
            <PromptBar onSubmit={(message) => send(message)} className="mt-3">
              <AttachmentChips attachments={attachments} />
              <SkillSlashTextarea
                value={input}
                onValueChange={setInput}
                placeholder={
                  waiting
                    ? "Approve or reject the action above…"
                      : showQuestion || showSkills
                        ? "Or reply directly…"
                        : "Send a message, / for commands…"
                }
                disabled={busy}
              />
              <PromptBarFooter>
                <PromptBarTools>
                  <AttachButton attachments={attachments} disabled={busy} />
                  <ModelPicker
                    value={model ?? context?.model ?? DEFAULT_MODEL}
                    onChange={setModel}
                  />
                </PromptBarTools>
                <PromptBarSubmit
                  status={busy ? "streaming" : status === "error" ? "error" : undefined}
                  onStop={stop}
                  disabled={
                    attachments.uploading ||
                    (!busy && !input.trim() && attachments.items.length === 0)
                  }
                />
              </PromptBarFooter>
            </PromptBar>
          </AttachmentDropZone>
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
          revision={changesRevision}
          prStep={prStep}
        />
      )}
    </div>
  );
}

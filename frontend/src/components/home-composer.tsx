"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/app/providers";
import { BranchPicker } from "@/components/branch-picker";
import { Pill } from "@/components/bui/button";
import {
  AttachButton,
  AttachmentChips,
  AttachmentDropZone,
  useComposerAttachments,
} from "@/components/composer-attachments";
import {
  PromptBar,
  PromptBarFooter,
  PromptBarSubmit,
  PromptBarTools,
} from "@/components/bui/prompt-bar";
import { EnvironmentPicker } from "@/components/environment-picker";
import { DEFAULT_MODEL, ModelPicker } from "@/components/model-picker";
import { RepoPicker } from "@/components/repo-picker";
import { SkillSlashTextarea } from "@/components/skill-slash-menu";
import {
  setComposerSelection,
  useComposerFocusTick,
  useComposerSelection,
} from "@/lib/composer-selection";
import { useBranches, useSandboxProviders, useStartChat } from "@/lib/queries";

export function HomeComposer() {
  const { auth, signIn } = useAuth();
  const connected = !!auth?.github.connected;
  const selection = useComposerSelection();
  const repo = connected ? selection.repo : null;
  const branches = useBranches(repo);
  const { data: providers } = useSandboxProviders();
  const startChat = useStartChat();
  const focusTick = useComposerFocusTick();
  const wrapperRef = useRef<HTMLDivElement>(null);

  const [text, setText] = useState("");
  const attachments = useComposerAttachments();
  const [pickedModel, setModel] = useState<string | null>(null);
  const model = pickedModel ?? selection.model ?? DEFAULT_MODEL;

  const branch =
    branches.data && !branches.data.some((b) => b.name === selection.branch)
      ? (branches.data.find((b) => b.default)?.name ?? null)
      : selection.branch;

  const remembered = providers?.find(
    (p) => p.id === selection.environment && p.available,
  );
  const environment =
    remembered?.id ?? providers?.find((p) => p.default)?.id ?? "local";

  useEffect(() => {
    wrapperRef.current?.querySelector("textarea")?.focus();
  }, [focusTick]);

  const pending = startChat.isPending || attachments.uploading;
  const canSend =
    !!repo && (!!text.trim() || attachments.items.length > 0) && !pending;

  async function send() {
    if (!canSend) return;
    const uploaded = await attachments.upload();
    if (!uploaded) return;
    startChat.mutate(
      {
        repo,
        branch,
        sandbox_provider: environment,
        model,
        initial_message: text.trim(),
        attachments: uploaded,
      },
      {
        onSuccess: () => {
          attachments.clear();
          setText("");
        },
      },
    );
  }

  return (
    <div className="flex w-full max-w-2xl flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1">
        <RepoPicker
          value={repo}
          disabled={!connected}
          onChange={(r) =>
            setComposerSelection({ repo: r.full_name, branch: r.default_branch })
          }
        />
        <BranchPicker
          value={repo ? branch : null}
          branches={branches.data}
          loading={branches.isPending}
          error={branches.isError}
          disabled={!repo}
          onChange={(b) => setComposerSelection({ branch: b })}
        />
        <EnvironmentPicker
          value={environment}
          providers={providers}
          onChange={(e) => setComposerSelection({ environment: e })}
        />
      </div>

      <div ref={wrapperRef}>
        <AttachmentDropZone attachments={attachments}>
          <PromptBar size="hero" onSubmit={send}>
            <AttachmentChips attachments={attachments} />
            <SkillSlashTextarea
              autoFocus
              value={text}
              onValueChange={setText}
              placeholder="Plan, build, / for commands"
              disabled={pending}
            />
            <PromptBarFooter>
              <PromptBarTools>
                <AttachButton attachments={attachments} disabled={pending} />
                <ModelPicker value={model} onChange={setModel} />
              </PromptBarTools>
              <PromptBarSubmit
                status={pending ? "submitted" : undefined}
                disabled={!canSend}
              />
            </PromptBarFooter>
          </PromptBar>
        </AttachmentDropZone>
      </div>

      {!connected && (
        <div className="flex justify-center pt-2">
          <Pill variant="secondary" size="sm" onClick={() => void signIn()}>
            <HugeiconsIcon icon={Github01Icon} className="size-4" />
            Connect your repos
          </Pill>
        </div>
      )}
    </div>
  );
}

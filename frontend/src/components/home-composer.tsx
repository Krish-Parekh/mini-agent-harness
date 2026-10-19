"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/app/providers";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { BranchPicker } from "@/components/branch-picker";
import { EnvironmentPicker } from "@/components/environment-picker";
import { DEFAULT_MODEL, ModelPicker } from "@/components/model-picker";
import { RepoPicker } from "@/components/repo-picker";
import { SkillChips, SkillSlashTextarea } from "@/components/skill-slash-menu";
import { Button } from "@/components/ui/button";
import type { Skill } from "@/lib/api";
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
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [skills, setSkills] = useState<Skill[]>([]);

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

  const canSend = !!repo && !!text.trim() && !startChat.isPending;

  function send() {
    if (!canSend) return;
    startChat.mutate({
      repo,
      branch,
      sandbox_provider: environment,
      model,
      initial_message: text.trim(),
      skill_ids: skills.map((s) => s.id),
    });
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
        <PromptInput onSubmit={send}>
          <SkillChips
            skills={skills}
            onRemove={(skill) =>
              setSkills((prev) => prev.filter((s) => s.id !== skill.id))
            }
          />
          <PromptInputBody>
            <SkillSlashTextarea
              autoFocus
              value={text}
              onValueChange={setText}
              excludeIds={skills.map((s) => s.id)}
              onPickSkill={(skill) => setSkills((prev) => [...prev, skill])}
              placeholder="Plan, build, / for skills"
              disabled={startChat.isPending}
            />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              <ModelPicker value={model} onChange={setModel} />
            </PromptInputTools>
            <PromptInputSubmit
              status={startChat.isPending ? "submitted" : undefined}
              disabled={!canSend}
            />
          </PromptInputFooter>
        </PromptInput>
      </div>

      {!connected && (
        <div className="flex justify-center pt-2">
          <Button variant="outline" onClick={() => void signIn()}>
            <HugeiconsIcon icon={Github01Icon} data-icon="inline-start" />
            Connect your repos
          </Button>
        </div>
      )}
    </div>
  );
}

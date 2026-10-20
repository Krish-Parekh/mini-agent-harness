"use client";

import { SparklesIcon } from "lucide-react";
import { useState } from "react";

import { ApprovalCard, ChoiceMark } from "@/components/bui/approval-card";
import { Pill } from "@/components/bui/button";
import { GlideMenu } from "@/components/bui/glide-menu";
import { ValuePill } from "@/components/bui/value-pill";
import { cn } from "@/lib/utils";

export type ProposedSkill = {
  source: string;
  skill_id: string;
  name: string;
  description?: string;
  installs?: number;
};

export type SkillProposalOutcome =
  | { kind: "included"; names: string[] }
  | { kind: "skipped" };

const INCLUDED_PREFIX = "Included skills: ";
const INCLUDED_SUFFIX = ". Continue with the task using them.";
export const SKIPPED_SKILLS_MESSAGE = "Skipped the proposed skills. Continue without them.";

export function includedSkillsMessage(names: string[]) {
  return `${INCLUDED_PREFIX}${names.join(", ")}${INCLUDED_SUFFIX}`;
}

export function skillReplyOutcome(text: string): SkillProposalOutcome | undefined {
  const trimmed = text.trim();
  if (trimmed === SKIPPED_SKILLS_MESSAGE) return { kind: "skipped" };
  if (!trimmed.startsWith(INCLUDED_PREFIX) || !trimmed.endsWith(INCLUDED_SUFFIX)) return undefined;
  const names = trimmed
    .slice(INCLUDED_PREFIX.length, -INCLUDED_SUFFIX.length)
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  return { kind: "included", names };
}

const compact = new Intl.NumberFormat("en", { notation: "compact" });

const skillKey = (skill: ProposedSkill) => `${skill.source}/${skill.skill_id}`;

export function formatInstalls(installs: number | undefined) {
  const n = installs ?? 0;
  return `${compact.format(n)} install${n === 1 ? "" : "s"}`;
}

export function SkillProposalCard({
  repo,
  reason,
  skills,
  onInstall,
  onInclude,
  onSkip,
}: {
  repo: string | null;
  reason?: string;
  skills: ProposedSkill[];
  onInstall: (skill: ProposedSkill) => Promise<{ name: string }>;
  onInclude: (names: string[]) => void;
  onSkip: () => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(() => new Set(skills.map(skillKey)));
  const [installed, setInstalled] = useState<Map<string, string>>(() => new Map());
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = skills.filter((s) => checked.has(skillKey(s)));
  const installing = progress !== null;

  const toggle = (key: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const include = async () => {
    if (!repo || selected.length === 0) return;
    setError(null);
    const names = new Map(installed);
    for (let i = 0; i < selected.length; i++) {
      const skill = selected[i];
      const key = skillKey(skill);
      setProgress(i);
      if (names.has(key)) continue;
      try {
        const result = await onInstall(skill);
        names.set(key, result.name);
        setInstalled(new Map(names));
      } catch (e) {
        setProgress(null);
        setError(`Couldn't include ${skill.name}: ${e instanceof Error ? e.message : String(e)}`);
        return;
      }
    }
    setProgress(null);
    onInclude(selected.map((s) => names.get(skillKey(s)) ?? s.name));
  };

  return (
    <ApprovalCard
      footer={
        <>
          <span className="pl-0.5 text-[12.5px] text-ink-2 tabular-nums">
            {installing
              ? `Including ${Math.min((progress ?? 0) + 1, selected.length)} of ${selected.length}…`
              : `${selected.length} of ${skills.length} selected`}
          </span>
          <div className="-mr-0.5 flex items-center gap-1.5">
            <Pill variant="ghost" size="sm" disabled={installing} onClick={onSkip}>
              Skip
            </Pill>
            <Pill
              variant="brand"
              size="sm"
              disabled={installing || selected.length === 0 || !repo}
              onClick={() => void include()}
            >
              {installing ? "Including…" : "Include"}
            </Pill>
          </div>
        </>
      }
    >
      <div className="flex items-start gap-2">
        <SparklesIcon className="mt-0.5 size-3.5 shrink-0 text-brand" />
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-ink">
            Skills for {repo ?? "this project"}
          </div>
          {reason && <div className="mt-0.5 text-[12.5px] text-ink-3">{reason}</div>}
        </div>
      </div>
      <GlideMenu
        className="mt-2.5 flex flex-col gap-0.5"
        highlightClassName="inset-x-0 rounded-control bg-hover"
      >
        {skills.map((skill) => {
          const key = skillKey(skill);
          const on = checked.has(key);
          return (
            <button
              key={key}
              type="button"
              role="checkbox"
              aria-checked={on}
              data-menu-row
              disabled={installing}
              onClick={() => toggle(key)}
              className="relative z-10 flex items-start gap-2 rounded-control px-1.5 py-1.5 text-left transition-colors duration-100 disabled:cursor-default"
            >
              <span className="mt-px">
                <ChoiceMark type="check" on={on} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span
                    className={cn(
                      "text-[13px] font-medium transition-colors duration-200",
                      on ? "text-ink" : "text-ink-2",
                    )}
                  >
                    {skill.name}
                  </span>
                  <span className="min-w-0 truncate font-mono text-[11.5px] text-ink-3">
                    {skill.source}
                  </span>
                  <ValuePill>{formatInstalls(skill.installs)}</ValuePill>
                </span>
                {skill.description && (
                  <span className="line-clamp-2 text-[12px] leading-snug text-ink-2">
                    {skill.description}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </GlideMenu>
      {error && (
        <div
          role="alert"
          className="mt-2 rounded-control bg-red-tint px-2.5 py-1.5 text-[12.5px] break-words text-red"
        >
          {error}
        </div>
      )}
    </ApprovalCard>
  );
}

export function SkillProposalSummary({
  skills,
  outcome,
}: {
  skills: ProposedSkill[];
  outcome?: SkillProposalOutcome;
}) {
  const label =
    outcome?.kind === "included"
      ? `Included ${outcome.names.length} skill${outcome.names.length === 1 ? "" : "s"}`
      : outcome?.kind === "skipped"
        ? "Skipped proposed skills"
        : `Proposed ${skills.length} skill${skills.length === 1 ? "" : "s"}`;
  const names = outcome?.kind === "included" ? outcome.names : skills.map((s) => s.name);
  return (
    <div
      className="flex w-full flex-wrap items-center gap-x-2 gap-y-1.5 rounded-card bg-surface px-3 py-2.5 shadow-card"
      style={{ animation: "fade-up 380ms var(--ease-out-strong) both" }}
    >
      <span className="flex items-center gap-2 text-[13px] font-medium text-ink">
        <SparklesIcon className="size-3.5 text-ink-3" />
        {label}
      </span>
      {names.map((name) => (
        <ValuePill
          key={name}
          tone={outcome?.kind === "included" ? "brand" : "neutral"}
          className={cn(outcome?.kind === "skipped" && "line-through")}
        >
          {name}
        </ValuePill>
      ))}
    </div>
  );
}

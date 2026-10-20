"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRightIcon, SparklesIcon } from "lucide-react";
import { toast } from "sonner";

import { Pill } from "@/components/bui/button";
import { GlideMenu } from "@/components/bui/glide-menu";
import { LoadingState } from "@/components/bui/loading-state";
import { ValuePill } from "@/components/bui/value-pill";
import { SettingsPage } from "@/components/settings/settings-ui";
import { api, type Skill } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { queryKeys, useSkills } from "@/lib/queries";

const UNUSED = "Not used in any project";

function groupByRepo(skills: Skill[]) {
  const byName = (a: Skill, b: Skill) => a.name.localeCompare(b.name);
  const repos = new Map<string, Skill[]>();
  const unused: Skill[] = [];
  for (const skill of skills) {
    if (skill.repos.length === 0) unused.push(skill);
    for (const repo of skill.repos) {
      const list = repos.get(repo) ?? [];
      list.push(skill);
      repos.set(repo, list);
    }
  }
  return {
    repos: [...repos.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([repo, list]) => ({ repo, skills: list.sort(byName) })),
    unused: unused.sort(byName),
  };
}

function SkillRow({
  skill,
  action,
  busy,
  onAction,
}: {
  skill: Skill;
  action: string;
  busy: boolean;
  onAction: () => void;
}) {
  return (
    <div
      data-menu-row
      className="relative z-10 flex items-center justify-between gap-4 rounded-control px-2.5 py-2"
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[13.5px] font-medium text-ink">{skill.name}</span>
          {skill.source_url && (
            <a
              href={skill.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex shrink-0 items-center gap-0.5 text-[12px] text-ink-3 transition-colors duration-100 hover:text-brand-ink"
            >
              {skill.registry_id ? "skills.sh" : "source"}
              <ArrowUpRightIcon className="size-3" />
            </a>
          )}
        </div>
        <p className="truncate text-[12.5px] text-ink-2">
          {skill.description || "No description"}
        </p>
      </div>
      <Pill variant="ghost" size="xs" disabled={busy} onClick={onAction} className="shrink-0">
        {action}
      </Pill>
    </div>
  );
}

function SkillGroup({
  title,
  mono,
  count,
  children,
}: {
  title: string;
  mono?: boolean;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-2 px-1">
        <h2 className={mono ? "font-mono text-[12.5px] text-ink-2" : "text-[13px] text-ink-2"}>
          {title}
        </h2>
        <ValuePill>{count}</ValuePill>
      </div>
      <GlideMenu
        className="flex flex-col rounded-card bg-surface p-1 shadow-card"
        highlightClassName="inset-x-1 rounded-control bg-hover"
      >
        {children}
      </GlideMenu>
    </section>
  );
}

export default function SkillsSettingsPage() {
  const queryClient = useQueryClient();
  const { data: skills, isPending } = useSkills();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.skills });

  const removeFromRepo = useMutation({
    mutationFn: ({ id, repo }: { id: string; repo: string }) =>
      api.setSkillRepo(id, repo, false),
    onSuccess: invalidate,
    onError: (e) => toast.error(messageFor(e)),
  });

  const deleteSkill = useMutation({
    mutationFn: (id: string) => api.deleteSkill(id),
    onSuccess: invalidate,
    onError: (e) => toast.error(messageFor(e)),
  });

  const groups = skills ? groupByRepo(skills) : null;

  return (
    <SettingsPage title="Skills">
      <p className="-mt-5 text-[13px] text-ink-3">
        Skills from skills.sh, included per project. A skill is active in every chat on the
        projects it&apos;s included in.
      </p>

      {isPending ? (
        <LoadingState label="Loading skills" />
      ) : !skills?.length || !groups ? (
        <div className="flex flex-col items-center gap-2 rounded-card bg-surface px-6 py-10 text-center shadow-card">
          <span className="flex size-8 items-center justify-center rounded-full bg-brand-tint text-brand">
            <SparklesIcon className="size-4" />
          </span>
          <p className="text-[14px] font-medium text-ink">No skills yet</p>
          <p className="max-w-sm text-[13px] text-ink-3">
            In any chat, type{" "}
            <code className="rounded-chip bg-field px-1 py-0.5 font-mono text-[12px] text-ink-2 shadow-hairline">
              /find-skill
            </code>{" "}
            followed by what you need. The agent searches skills.sh and proposes skills to
            include for that project.
          </p>
        </div>
      ) : (
        <>
          {groups.repos.map(({ repo, skills: list }) => (
            <SkillGroup key={repo} title={repo} mono count={list.length}>
              {list.map((skill) => (
                <SkillRow
                  key={skill.id}
                  skill={skill}
                  action={`Remove from ${repo}`}
                  busy={
                    removeFromRepo.isPending &&
                    removeFromRepo.variables?.id === skill.id &&
                    removeFromRepo.variables.repo === repo
                  }
                  onAction={() => removeFromRepo.mutate({ id: skill.id, repo })}
                />
              ))}
            </SkillGroup>
          ))}
          {groups.unused.length > 0 && (
            <SkillGroup title={UNUSED} count={groups.unused.length}>
              {groups.unused.map((skill) => (
                <SkillRow
                  key={skill.id}
                  skill={skill}
                  action="Delete"
                  busy={deleteSkill.isPending && deleteSkill.variables === skill.id}
                  onAction={() => deleteSkill.mutate(skill.id)}
                />
              ))}
            </SkillGroup>
          )}
        </>
      )}
    </SettingsPage>
  );
}

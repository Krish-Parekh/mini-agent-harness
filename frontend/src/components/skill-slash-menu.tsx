"use client";

import { Cancel01Icon, SparklesIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import {
  type ChangeEvent,
  type ComponentProps,
  type KeyboardEvent,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  PromptInputHeader,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Badge } from "@/components/ui/badge";
import type { Skill } from "@/lib/api";
import { useSkills } from "@/lib/queries";
import { cn } from "@/lib/utils";

const MAX_RESULTS = 8;

function isSpace(ch: string | undefined) {
  return ch === " " || ch === "\n" || ch === "\t";
}

export function activeSlash(
  value: string,
  cursor: number,
): { start: number; query: string } | null {
  for (let i = cursor - 1; i >= 0; i--) {
    const ch = value[i];
    if (isSpace(ch)) return null;
    if (ch === "/") {
      return i === 0 || isSpace(value[i - 1])
        ? { start: i, query: value.slice(i + 1, cursor) }
        : null;
    }
  }
  return null;
}

type Props = Omit<
  ComponentProps<typeof PromptInputTextarea>,
  "value" | "onChange"
> & {
  value: string;
  onValueChange: (value: string) => void;
  onPickSkill: (skill: Skill) => void;
  excludeIds?: string[];
};

export function SkillSlashTextarea({
  value,
  onValueChange,
  onPickSkill,
  excludeIds = [],
  ...props
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [slash, setSlash] = useState<{ start: number; query: string } | null>(
    null,
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const { data: skills } = useSkills();

  const q = slash?.query.toLowerCase() ?? "";
  const results = slash
    ? (skills ?? [])
        .filter((s) => !excludeIds.includes(s.id))
        .filter((s) => !q || s.name.toLowerCase().includes(q))
        .slice(0, MAX_RESULTS)
    : [];
  const showEmptyHint = !!slash && !q && skills?.length === 0;
  const open = results.length > 0 || showEmptyHint;
  const index = Math.min(activeIndex, results.length - 1);

  const textareaEl = () => wrapperRef.current?.querySelector("textarea") ?? null;

  useLayoutEffect(() => {
    if (!open) return;
    const textarea = textareaEl();
    const anchor = textarea?.closest("form") ?? textarea;
    const menu = menuRef.current;
    if (!anchor || !menu) return;
    const r = anchor.getBoundingClientRect();
    const below = window.innerHeight - r.bottom > menu.offsetHeight + 16;
    menu.style.left = `${r.left}px`;
    menu.style.width = `${Math.min(r.width, 420)}px`;
    menu.style.top = below ? `${r.bottom + 8}px` : "";
    menu.style.bottom = below ? "" : `${window.innerHeight - r.top + 8}px`;
  }, [open, value]);

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onValueChange(e.target.value);
    const caret = e.target.selectionStart ?? e.target.value.length;
    setSlash(activeSlash(e.target.value, caret));
    setActiveIndex(0);
  }

  function pick(skill: Skill) {
    const el = textareaEl();
    if (!slash) return;
    const before = value.slice(0, slash.start);
    const after = value.slice(el?.selectionStart ?? value.length);
    onValueChange(before + after.replace(/^ /, ""));
    setSlash(null);
    onPickSkill(skill);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(before.length, before.length);
    });
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setSlash(null);
      return;
    }
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((index + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((index - 1 + results.length) % results.length);
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      pick(results[index]);
    }
  }

  return (
    <div ref={wrapperRef} className="contents">
      {open &&
        createPortal(
          <div
            ref={menuRef}
            role="listbox"
            aria-label="Skills"
            className="fixed z-50 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-md"
          >
            <p className="px-3 pt-2 pb-1 text-xs font-medium text-muted-foreground">
              Skills
            </p>
            {showEmptyHint ? (
              <p className="px-3 pb-3 text-sm text-muted-foreground">
                No skills yet.{" "}
                <Link
                  href="/settings/skills"
                  onMouseDown={(e) => e.preventDefault()}
                  className="underline"
                >
                  Add one in Settings
                </Link>
              </p>
            ) : (
              <ul className="max-h-64 overflow-y-auto p-1">
                {results.map((skill, i) => (
                  <li key={skill.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={i === index}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => pick(skill)}
                      onMouseEnter={() => setActiveIndex(i)}
                      className={cn(
                        "flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left",
                        i === index && "bg-accent text-accent-foreground",
                      )}
                    >
                      <span className="text-sm font-medium">/{skill.name}</span>
                      {skill.description && (
                        <span className="line-clamp-1 text-xs text-muted-foreground">
                          {skill.description}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>,
          document.body,
        )}
      <PromptInputTextarea
        {...props}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={() => setSlash(null)}
      />
    </div>
  );
}

export function SkillChips({
  skills,
  onRemove,
}: {
  skills: Skill[];
  onRemove: (skill: Skill) => void;
}) {
  if (!skills.length) return null;
  return (
    <PromptInputHeader className="justify-start px-3 pt-2.5">
      {skills.map((skill) => (
        <Badge key={skill.id} variant="secondary" className="gap-1 pr-1">
          <HugeiconsIcon icon={SparklesIcon} data-icon="inline-start" />
          {skill.name}
          <button
            type="button"
            aria-label={`Remove ${skill.name}`}
            onClick={() => onRemove(skill)}
            className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
          >
            <HugeiconsIcon icon={Cancel01Icon} className="size-3" />
          </button>
        </Badge>
      ))}
    </PromptInputHeader>
  );
}

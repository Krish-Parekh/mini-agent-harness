"use client";

import { SparklesIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import {
  type ChangeEvent,
  type KeyboardEvent,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  PromptBarChip,
  PromptBarHeader,
  PromptBarMenu,
  PromptBarMenuRow,
  PromptBarTextarea,
  type PromptBarTextareaProps,
} from "@/components/bui/prompt-bar";
import type { Skill } from "@/lib/api";
import { useSkills } from "@/lib/queries";

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

type Props = Omit<PromptBarTextareaProps, "value" | "onChange"> & {
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
    menu.style.transformOrigin = below ? "top center" : "bottom center";
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
          <PromptBarMenu
            ref={menuRef}
            role="listbox"
            aria-label="Skills"
            label="Skills"
            activeIndex={index}
            hint={showEmptyHint ? undefined : "Type to search skills"}
          >
            {showEmptyHint ? (
              <p className="px-2 pb-2 text-[12px] text-ink-3">
                No skills yet.{" "}
                <Link
                  href="/settings/skills"
                  onMouseDown={(e) => e.preventDefault()}
                  className="font-medium text-brand-ink hover:underline"
                >
                  Add one in Settings
                </Link>
              </p>
            ) : (
              results.map((skill, i) => (
                <PromptBarMenuRow
                  key={skill.id}
                  active={i === index}
                  onClick={() => pick(skill)}
                  onMouseEnter={() => setActiveIndex(i)}
                >
                  <span className="flex size-5.5 shrink-0 items-center justify-center text-ink-2">
                    <HugeiconsIcon icon={SparklesIcon} className="size-[15px]" />
                  </span>
                  <span className="shrink-0 text-[12.5px] font-medium text-ink">
                    /{skill.name}
                  </span>
                  {skill.description && (
                    <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">
                      {skill.description}
                    </span>
                  )}
                </PromptBarMenuRow>
              ))
            )}
          </PromptBarMenu>,
          document.body,
        )}
      <PromptBarTextarea
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
    <PromptBarHeader>
      {skills.map((skill) => (
        <PromptBarChip
          key={skill.id}
          icon={<HugeiconsIcon icon={SparklesIcon} className="size-3 text-brand" />}
          label={skill.name}
          removeLabel={`Remove ${skill.name}`}
          onRemove={() => onRemove(skill)}
        />
      ))}
    </PromptBarHeader>
  );
}

"use client";

import { Search01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  type ChangeEvent,
  type KeyboardEvent,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  PromptBarMenu,
  PromptBarMenuRow,
  PromptBarTextarea,
  type PromptBarTextareaProps,
} from "@/components/bui/prompt-bar";

const COMMANDS = [
  {
    name: "find-skill",
    description: "Find skills on skills.sh for this project",
  },
];

type Command = (typeof COMMANDS)[number];

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
      return value.slice(0, i).trim() === ""
        ? { start: i, query: value.slice(i + 1, cursor) }
        : null;
    }
  }
  return null;
}

type Props = Omit<PromptBarTextareaProps, "value" | "onChange"> & {
  value: string;
  onValueChange: (value: string) => void;
};

export function SkillSlashTextarea({ value, onValueChange, ...props }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [slash, setSlash] = useState<{ start: number; query: string } | null>(
    null,
  );
  const [activeIndex, setActiveIndex] = useState(0);

  const q = slash?.query.toLowerCase() ?? "";
  const results = slash ? COMMANDS.filter((c) => c.name.startsWith(q)) : [];
  const open = results.length > 0;
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

  function pick(command: Command) {
    const el = textareaEl();
    if (!slash) return;
    const before = value.slice(0, slash.start);
    const after = value.slice(el?.selectionStart ?? value.length);
    const inserted = `${before}/${command.name} `;
    onValueChange(inserted + after.replace(/^ /, ""));
    setSlash(null);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(inserted.length, inserted.length);
    });
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!open) {
      props.onKeyDown?.(e);
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setSlash(null);
    } else if (e.key === "ArrowDown") {
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
            aria-label="Commands"
            label="Commands"
            activeIndex={index}
          >
            {results.map((command, i) => (
              <PromptBarMenuRow
                key={command.name}
                active={i === index}
                onClick={() => pick(command)}
                onMouseEnter={() => setActiveIndex(i)}
              >
                <span className="flex size-5.5 shrink-0 items-center justify-center text-ink-2">
                  <HugeiconsIcon icon={Search01Icon} className="size-[15px]" />
                </span>
                <span className="shrink-0 text-[12.5px] font-medium text-ink">
                  /{command.name}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">
                  {command.description}
                </span>
              </PromptBarMenuRow>
            ))}
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

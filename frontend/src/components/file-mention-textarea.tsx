"use client";

import {
  type ChangeEvent,
  type KeyboardEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  Glyph,
  PromptBarMenu,
  PromptBarMenuRow,
  PromptBarTextarea,
  type PromptBarTextareaProps,
} from "@/components/bui/prompt-bar";
import { useFiles } from "@/lib/queries";

const MAX_RESULTS = 8;

function activeMention(
  value: string,
  cursor: number,
): { start: number; query: string } | null {
  for (let i = cursor - 1; i >= 0; i--) {
    const ch = value[i];
    if (ch === " " || ch === "\n" || ch === "\t") return null;
    if (ch === "@") {
      const before = value[i - 1];
      const atBoundary =
        i === 0 || before === " " || before === "\n" || before === "\t";
      return atBoundary ? { start: i, query: value.slice(i + 1, cursor) } : null;
    }
  }
  return null;
}

type Props = Omit<PromptBarTextareaProps, "value" | "onChange"> & {
  value: string;
  onValueChange: (value: string) => void;
  conversationId: string;
};

export function FileMentionTextarea({
  value,
  onValueChange,
  conversationId,
  ...props
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [mention, setMention] = useState<{ start: number; query: string } | null>(
    null,
  );
  const [activeIndex, setActiveIndex] = useState(0);

  const { data: files } = useFiles(conversationId, mention !== null);

  const results = useMemo(() => {
    if (!mention || !files) return [];
    const q = mention.query.toLowerCase();
    const matched = q ? files.filter((f) => f.toLowerCase().includes(q)) : files;
    return matched.slice(0, MAX_RESULTS);
  }, [mention, files]);

  const open = mention !== null && results.length > 0;
  const index = Math.min(activeIndex, results.length - 1);

  const textareaEl = () => wrapperRef.current?.querySelector("textarea") ?? null;

  useLayoutEffect(() => {
    if (!open) return;
    const anchor = textareaEl();
    const menu = menuRef.current;
    if (!anchor || !menu) return;
    const r = anchor.getBoundingClientRect();
    menu.style.left = `${r.left}px`;
    menu.style.bottom = `${window.innerHeight - r.top + 8}px`;
    menu.style.width = `${r.width}px`;
  }, [open, value]);

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onValueChange(e.target.value);
    const caret = e.target.selectionStart ?? e.target.value.length;
    setMention(activeMention(e.target.value, caret));
    setActiveIndex(0);
  }

  function selectFile(path: string) {
    const el = textareaEl();
    if (!el || !mention) return;
    const before = value.slice(0, mention.start);
    const after = value.slice(el.selectionStart ?? value.length);
    const insert = `@${path} `;
    onValueChange(before + insert + after);
    setMention(null);
    const caret = before.length + insert.length;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (Math.min(i, results.length - 1) + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex(
        (i) =>
          (Math.min(i, results.length - 1) - 1 + results.length) %
          results.length,
      );
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      selectFile(results[index]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setMention(null);
    }
  }

  return (
    <div ref={wrapperRef} className="contents">
      {open &&
        createPortal(
          <PromptBarMenu
            ref={menuRef}
            role="listbox"
            aria-label="Files"
            activeIndex={index}
            hint="Type to search files"
            className="bottom-0 left-0"
          >
            {results.map((path, i) => (
              <PromptBarMenuRow
                key={path}
                active={i === index}
                onClick={() => selectFile(path)}
                onMouseEnter={() => setActiveIndex(i)}
              >
                <span className="flex size-5.5 shrink-0 items-center justify-center text-ink-2">
                  <Glyph size={14}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <path d="M14 2v6h6" />
                  </Glyph>
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink">
                  {path}
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
        onBlur={() => setMention(null)}
      />
    </div>
  );
}

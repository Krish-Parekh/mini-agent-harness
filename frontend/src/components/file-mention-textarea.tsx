"use client";

import {
  type ChangeEvent,
  type ComponentProps,
  type KeyboardEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { PromptInputTextarea } from "@/components/ai-elements/prompt-input";
import { useFiles } from "@/lib/queries";
import { cn } from "@/lib/utils";

const MAX_RESULTS = 8;

// Find an active "@mention" token that the cursor sits inside. Walks back from
// the caret to the nearest '@'; returns null if a whitespace is hit first or
// the '@' is mid-word (e.g. an email address), so we don't hijack those.
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

type Props = Omit<
  ComponentProps<typeof PromptInputTextarea>,
  "value" | "onChange"
> & {
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

  // Only fetch the file list once the user actually opens a mention.
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

  // Anchor the portaled menu to the textarea by writing straight to the menu
  // node's style (no React-managed style prop, so hover re-renders can't clobber
  // it). Recompute on open and on value change, since the auto-growing textarea
  // shifts its own top edge.
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
    // Restore focus and drop the caret just past the inserted mention.
    const caret = before.length + insert.length;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!open) return;
    // preventDefault here also stops PromptInputTextarea's Enter-to-submit,
    // which bails when the event was already defaultPrevented.
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
          <div
            ref={menuRef}
            className="fixed bottom-0 left-0 z-50 overflow-hidden rounded-lg border bg-popover shadow-md"
          >
            <ul className="max-h-64 overflow-y-auto p-1">
              {results.map((path, i) => (
                <li key={path}>
                  <button
                    type="button"
                    // Keep focus on the textarea so the click selects instead
                    // of blurring the menu shut first.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectFile(path)}
                    onMouseEnter={() => setActiveIndex(i)}
                    className={cn(
                      "flex w-full items-center rounded-md px-2 py-1.5 text-left",
                      i === index
                        ? "bg-accent text-accent-foreground"
                        : "text-foreground",
                    )}
                  >
                    <span className="truncate font-mono text-xs">{path}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>,
          document.body,
        )}
      <PromptInputTextarea
        {...props}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={() => setMention(null)}
      />
    </div>
  );
}

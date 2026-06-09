"use client";

import { useMemo, useState } from "react";
import {
  ArrowRightIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  PencilLineIcon,
  XIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type Question = {
  question: string;
  header?: string;
  options: string[];
  multi_select?: boolean;
};

type Answer = {
  selected: string[];
  custom: string;
  customActive: boolean;
  skipped: boolean;
};

const emptyAnswer = (): Answer => ({
  selected: [],
  custom: "",
  customActive: false,
  skipped: false,
});

function isResolved(a: Answer): boolean {
  return a.skipped || a.selected.length > 0 || a.custom.trim().length > 0;
}

function answerText(a: Answer): string {
  if (a.custom.trim()) return a.custom.trim();
  if (a.selected.length) return a.selected.join(", ");
  return "(skipped)";
}

/**
 * Wizard that renders the agent's `ask_user` questions one at a time and
 * composes the user's reply. Selecting (single-select) auto-advances; the reply
 * is submitted as a normal message so the agent resumes from it.
 */
export function QuestionCard({
  questions,
  onSubmit,
  onDismiss,
}: {
  questions: Question[];
  onSubmit: (text: string) => void;
  onDismiss: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Answer[]>(() =>
    questions.map(emptyAnswer),
  );

  const total = questions.length;
  const q = questions[index];
  const a = answers[index];
  const allResolved = useMemo(() => answers.every(isResolved), [answers]);

  function update(patch: Partial<Answer>) {
    setAnswers((prev) =>
      prev.map((it, i) => (i === index ? { ...it, ...patch } : it)),
    );
  }

  function advance() {
    setIndex((i) => Math.min(i + 1, total - 1));
  }

  function pick(option: string) {
    if (q.multi_select) {
      const has = a.selected.includes(option);
      update({
        selected: has
          ? a.selected.filter((o) => o !== option)
          : [...a.selected, option],
        skipped: false,
        customActive: false,
      });
      return;
    }
    update({ selected: [option], custom: "", customActive: false, skipped: false });
    if (index < total - 1) advance();
  }

  function submit() {
    const text = questions
      .map((question, i) => `${i + 1}. ${question.question} → ${answerText(answers[i])}`)
      .join("\n");
    onSubmit(text);
  }

  return (
    <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          {q.header && (
            <span className="text-muted-foreground text-xs">{q.header}</span>
          )}
          <h3 className="truncate font-medium text-sm">{q.question}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-1 text-muted-foreground">
          <button
            type="button"
            onClick={() => setIndex((i) => Math.max(i - 1, 0))}
            disabled={index === 0}
            aria-label="Previous question"
            className="rounded p-1 hover:bg-muted/60 disabled:opacity-30"
          >
            <ChevronLeftIcon className="size-4" />
          </button>
          <span className="text-xs tabular-nums">
            {index + 1} of {total}
          </span>
          <button
            type="button"
            onClick={advance}
            disabled={index === total - 1}
            aria-label="Next question"
            className="rounded p-1 hover:bg-muted/60 disabled:opacity-30"
          >
            <ChevronRightIcon className="size-4" />
          </button>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss questions"
            className="ml-1 rounded p-1 hover:bg-muted/60"
          >
            <XIcon className="size-4" />
          </button>
        </div>
      </div>

      <ul className="divide-y">
        {q.options.map((option, i) => {
          const selected = a.selected.includes(option);
          return (
            <li key={option}>
              <button
                type="button"
                onClick={() => pick(option)}
                className={cn(
                  "group flex w-full items-center gap-3 px-4 py-3 text-left text-sm transition-colors",
                  selected ? "bg-muted/70" : "hover:bg-muted/40",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-md border text-xs tabular-nums",
                    selected
                      ? "border-foreground bg-foreground text-background"
                      : "text-muted-foreground",
                  )}
                >
                  {selected ? <CheckIcon className="size-3.5" /> : i + 1}
                </span>
                <span className={cn(!selected && "text-foreground/90")}>
                  {option}
                </span>
                {selected && !q.multi_select && (
                  <ArrowRightIcon className="ml-auto size-4 text-muted-foreground" />
                )}
              </button>
            </li>
          );
        })}

        <li className="flex items-center gap-3 px-4 py-3">
          <button
            type="button"
            onClick={() => update({ customActive: !a.customActive, skipped: false })}
            aria-label="Something else"
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
          >
            <PencilLineIcon className="size-3.5" />
          </button>
          {a.customActive ? (
            <input
              autoFocus
              value={a.custom}
              onChange={(e) => update({ custom: e.target.value })}
              placeholder="Type your own answer…"
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          ) : (
            <button
              type="button"
              onClick={() => update({ customActive: true, skipped: false })}
              className="flex-1 text-left text-muted-foreground text-sm"
            >
              Something else
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              update({ skipped: true });
              if (index < total - 1) advance();
            }}
            className="rounded-md border px-3 py-1 text-xs hover:bg-muted/60"
          >
            Skip
          </button>
        </li>
      </ul>

      <div className="flex items-center justify-between gap-3 border-t px-4 py-2.5">
        <span className="text-muted-foreground text-xs">
          {allResolved
            ? "All set — submit your answers."
            : `${answers.filter(isResolved).length}/${total} answered`}
        </span>
        <button
          type="button"
          onClick={submit}
          disabled={!allResolved}
          className="rounded-md bg-foreground px-3 py-1.5 text-background text-xs font-medium hover:bg-foreground/90 disabled:opacity-40"
        >
          Submit answers
        </button>
      </div>
    </div>
  );
}

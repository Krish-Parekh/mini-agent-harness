"use client";

import { useMemo, useState } from "react";

import { ApprovalCard, ApprovalIcon, ChoiceMark } from "@/components/bui/approval-card";
import { Pill } from "@/components/bui/button";
import { GlideMenu } from "@/components/bui/glide-menu";
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
  skipped: boolean;
};

const emptyAnswer = (): Answer => ({ selected: [], custom: "", skipped: false });

function isResolved(a: Answer): boolean {
  return a.skipped || a.selected.length > 0 || a.custom.trim().length > 0;
}

function hasAnswer(a: Answer): boolean {
  return a.selected.length > 0 || a.custom.trim().length > 0;
}

function answerText(a: Answer): string {
  if (a.custom.trim()) return a.custom.trim();
  if (a.selected.length) return a.selected.join(", ");
  return "(skipped)";
}

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
  const [answers, setAnswers] = useState<Answer[]>(() => questions.map(emptyAnswer));

  const total = questions.length;
  const q = questions[index];
  const a = answers[index];
  const last = index === total - 1;
  const allResolved = useMemo(() => answers.every(isResolved), [answers]);
  const answered = answers.filter(isResolved).length;

  if (!q || !a) return null;

  const update = (patch: Partial<Answer>) =>
    setAnswers((prev) => prev.map((it, i) => (i === index ? { ...it, ...patch } : it)));

  const goTo = (next: number) => setIndex(Math.min(Math.max(next, 0), total - 1));

  const submit = () => {
    const text = questions
      .map((question, i) => `${i + 1}. ${question.question} → ${answerText(answers[i])}`)
      .join("\n");
    onSubmit(text);
  };

  const pick = (option: string) => {
    if (q.multi_select) {
      const has = a.selected.includes(option);
      update({
        selected: has ? a.selected.filter((o) => o !== option) : [...a.selected, option],
        skipped: false,
      });
      return;
    }
    update({ selected: [option], custom: "", skipped: false });
    if (!last) goTo(index + 1);
  };

  const skip = () => {
    update({ skipped: true });
    if (!last) goTo(index + 1);
  };

  const proceed = () => {
    if (last) {
      if (allResolved) submit();
      return;
    }
    goTo(index + 1);
  };

  const type = q.multi_select ? "check" : "radio";
  const primaryDisabled = last ? !allResolved : !hasAnswer(a);

  return (
    <ApprovalCard
      onDismiss={onDismiss}
      dismissLabel="Dismiss questions"
      footer={
        <>
          <div className="flex items-center gap-1 text-ink-3">
            <button
              type="button"
              aria-label="Previous question"
              disabled={index === 0}
              onClick={() => goTo(index - 1)}
              className="flex size-[18px] items-center justify-center rounded-[5px] transition-colors duration-100 enabled:hover:text-ink disabled:opacity-30"
            >
              <ApprovalIcon size={14} path={<path d="M18 15l-6-6-6 6" />} />
            </button>
            <span className="text-[12px] font-medium text-ink-3 tabular-nums" style={{ letterSpacing: "-0.1px" }}>
              <span key={index} className="inline-block" style={{ animation: "fade-up 250ms var(--ease-out-strong) both" }}>
                {index + 1}
              </span>{" "}
              / {total}
            </span>
            <button
              type="button"
              aria-label="Next question"
              disabled={last}
              onClick={() => goTo(index + 1)}
              className="flex size-[18px] items-center justify-center rounded-[5px] transition-colors duration-100 enabled:hover:text-ink disabled:opacity-30"
            >
              <ApprovalIcon size={14} path={<path d="M6 9l6 6 6-6" />} />
            </button>
            {last && !allResolved && (
              <span className="ml-1.5 text-[12px] text-ink-3 tabular-nums">
                {answered}/{total} answered
              </span>
            )}
          </div>
          <div className="-mr-0.5 flex items-center gap-1.5">
            <Pill variant="ghost" size="sm" onClick={skip}>
              Skip
            </Pill>
            <Pill variant="brand" size="sm" disabled={primaryDisabled} onClick={proceed}>
              {last ? "Submit answers" : "Continue"}
            </Pill>
          </div>
        </>
      }
    >
      <div key={index} aria-live="polite" style={{ animation: "fade-up 300ms var(--ease-out-strong) both" }}>
        {q.header && <div className="pr-8 text-[12px] text-ink-3">{q.header}</div>}
        <div className="pr-8 text-[14px] font-medium text-ink">{q.question}</div>
        <GlideMenu className="mt-2.5 flex flex-col gap-1" highlightClassName="inset-x-0 rounded-control bg-hover">
          {q.options.map((option) => {
            const on = a.selected.includes(option);
            return (
              <button
                key={option}
                type="button"
                data-menu-row
                aria-pressed={on}
                onClick={() => pick(option)}
                className="relative z-10 flex items-center gap-1.5 rounded-control py-1 pr-2 pl-1 text-left transition-colors duration-100"
              >
                <ChoiceMark type={type} on={on} />
                <span className={cn("text-[13px] leading-snug transition-colors duration-200", on ? "text-ink" : "text-ink-2")}>
                  {option}
                </span>
              </button>
            );
          })}
          <label data-menu-row className="relative z-10 flex items-center gap-1.5 rounded-control py-1 pr-2 pl-1 transition-colors duration-100">
            <input
              value={a.custom}
              onChange={(event) =>
                update({
                  custom: event.target.value,
                  skipped: false,
                  ...(q.multi_select ? {} : { selected: [] }),
                })
              }
              onKeyDown={(event) => {
                if (event.key === "Enter" && !primaryDisabled) {
                  event.preventDefault();
                  proceed();
                }
              }}
              placeholder="Something else…"
              aria-label="Custom answer"
              className="min-w-0 flex-1 bg-transparent pl-1.5 text-[13px] text-ink outline-none placeholder:text-ink-3"
            />
          </label>
        </GlideMenu>
      </div>
    </ApprovalCard>
  );
}

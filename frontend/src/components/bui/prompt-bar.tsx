"use client";

import {
  type ButtonHTMLAttributes,
  type ComponentProps,
  type FormEvent,
  type HTMLAttributes,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type Ref,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export function Glyph({
  children,
  size = 15,
  strokeWidth = 1.8,
  className,
}: {
  children: ReactNode;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      {children}
    </svg>
  );
}

export type PromptBarMessage = { text: string };

export function PromptBar({
  onSubmit,
  size = "chat",
  className,
  children,
}: {
  onSubmit: (
    message: PromptBarMessage,
    event: FormEvent<HTMLFormElement>,
  ) => void | Promise<void>;
  size?: "chat" | "hero";
  className?: string;
  children: ReactNode;
}) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = new FormData(event.currentTarget).get("message");
    void onSubmit({ text: typeof text === "string" ? text : "" }, event);
  }

  function focusInput(event: MouseEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return;
    event.currentTarget.querySelector("textarea")?.focus();
  }

  return (
    <form
      data-promptbar
      data-size={size}
      onSubmit={handleSubmit}
      className={cn("group/prompt-bar w-full", className)}
    >
      <div
        role="presentation"
        onClick={focusInput}
        className={cn(
          "relative isolate flex cursor-text flex-col overflow-hidden border border-line bg-surface shadow-card transition-[border-color] duration-150 focus-within:border-line-strong",
          size === "hero" ? "gap-2.5 rounded-[22px] p-3.5" : "gap-1.5 rounded-[14px] p-2",
        )}
      >
        {children}
      </div>
    </form>
  );
}

export function PromptBarHeader({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex flex-wrap gap-1.5 px-0.5 pt-0.5", className)}
      {...props}
    />
  );
}

export function PromptBarChip({
  icon,
  label,
  removeLabel,
  onRemove,
}: {
  icon?: ReactNode;
  label: string;
  removeLabel: string;
  onRemove: () => void;
}) {
  return (
    <span className="flex h-6.5 animate-[pop-in_200ms_var(--ease-out-strong)_both] items-center gap-1.5 rounded-chip bg-field py-1 pr-1 pl-1.5 text-[11.5px] text-ink-2 shadow-hairline">
      {icon}
      <span className="max-w-36 truncate">{label}</span>
      <button
        type="button"
        aria-label={removeLabel}
        onClick={onRemove}
        className="-my-1 flex size-6 items-center justify-center rounded-[5px] text-ink-3 transition-colors duration-100 hover:bg-line/70 hover:text-ink"
      >
        <Glyph size={10} strokeWidth={2.5}>
          <path d="M18 6L6 18M6 6l12 12" />
        </Glyph>
      </button>
    </span>
  );
}

export type PromptBarTextareaProps = ComponentProps<"textarea">;

export function PromptBarTextarea({
  onKeyDown,
  className,
  placeholder = "Write a message…",
  ...props
}: PromptBarTextareaProps) {
  const [composing, setComposing] = useState(false);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    if (event.key !== "Enter" || event.shiftKey) return;
    if (composing || event.nativeEvent.isComposing) return;
    event.preventDefault();
    const { form } = event.currentTarget;
    const submit = form?.querySelector<HTMLButtonElement>('button[type="submit"]');
    if (submit?.disabled) return;
    form?.requestSubmit();
  }

  return (
    <textarea
      name="message"
      rows={1}
      aria-label="Prompt"
      placeholder={placeholder}
      onKeyDown={handleKeyDown}
      onCompositionStart={() => setComposing(true)}
      onCompositionEnd={() => setComposing(false)}
      className={cn(
        "field-sizing-content min-h-10 max-h-48 w-full min-w-0 resize-none bg-transparent px-1.5 py-1 text-[14px] leading-5 text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3 disabled:cursor-not-allowed disabled:opacity-60",
        "group-data-[size=hero]/prompt-bar:min-h-[68px] group-data-[size=hero]/prompt-bar:px-2 group-data-[size=hero]/prompt-bar:py-2",
        className,
      )}
      {...props}
    />
  );
}

export function PromptBarFooter({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex items-center justify-between gap-1", className)}
      {...props}
    />
  );
}

export function PromptBarTools({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex min-w-0 items-center gap-1", className)}
      {...props}
    />
  );
}

export function PromptBarButton({
  className,
  type = "button",
  ref,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { ref?: Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "flex h-7 shrink-0 items-center gap-1 rounded-control px-1.5 text-[12px] font-medium text-ink-2 transition-colors duration-150 outline-none hover:bg-hover hover:text-ink focus-visible:bg-hover focus-visible:text-ink aria-expanded:bg-hover aria-expanded:text-ink disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export type PromptBarStatus = "submitted" | "streaming" | "error" | undefined;

export function PromptBarSubmit({
  status,
  onStop,
  disabled,
  className,
}: {
  status?: PromptBarStatus;
  onStop?: () => void;
  disabled?: boolean;
  className?: string;
}) {
  const generating = status === "submitted" || status === "streaming";
  const stoppable = generating && !!onStop;

  return (
    <button
      type={stoppable ? "button" : "submit"}
      aria-label={generating ? "Stop" : "Send"}
      disabled={disabled}
      onClick={
        stoppable
          ? (event) => {
              event.preventDefault();
              onStop?.();
            }
          : undefined
      }
      className={cn(
        "flex size-7 shrink-0 items-center justify-center rounded-control bg-ink text-surface transition-[background-color,color,transform] duration-200 enabled:active:scale-[0.94] disabled:bg-line-strong disabled:text-ink-2",
        className,
      )}
    >
      {status === "submitted" ? (
        <Spinner className="size-3.5" />
      ) : status === "streaming" ? (
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <rect width="10" height="10" rx="2" fill="currentColor" />
        </svg>
      ) : (
        <Glyph size={16} strokeWidth={2.4}>
          <path d="M12 19V5M5 12l7-7 7 7" />
        </Glyph>
      )}
    </button>
  );
}

export function PromptBarMenu({
  ref,
  activeIndex,
  label,
  hint,
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  ref?: Ref<HTMLDivElement>;
  activeIndex: number;
  label?: string;
  hint?: ReactNode;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const glideRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const glide = glideRef.current;
    const row = listRef.current?.querySelectorAll<HTMLElement>("[data-menu-row]")[
      activeIndex
    ];
    if (!glide) return;
    if (!row) {
      glide.style.opacity = "0";
      return;
    }
    glide.style.transform = `translateY(${row.offsetTop}px)`;
    glide.style.height = `${row.offsetHeight}px`;
    glide.style.opacity = "1";
  });

  return (
    <div
      ref={ref}
      className={cn(
        "fixed z-50 origin-bottom animate-[pop-in_180ms_var(--ease-out-strong)_both] overflow-hidden rounded-card bg-surface p-1 text-ink shadow-raised",
        className,
      )}
      {...props}
    >
      {label && (
        <p className="px-2 pt-1 pb-1.5 text-[11px] font-medium text-ink-3">{label}</p>
      )}
      <div ref={listRef} className="relative max-h-64 overflow-y-auto">
        <span
          ref={glideRef}
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 rounded-[6px] bg-hover opacity-0 transition-[transform,height,opacity] duration-200 ease-(--ease-out-strong)"
        />
        {children}
      </div>
      {hint && (
        <div className="mt-1 border-t border-line px-2 pt-1.5 pb-1 text-[11px] text-ink-3">
          {hint}
        </div>
      )}
    </div>
  );
}

export function PromptBarMenuRow({
  active,
  className,
  ...props
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & { active: boolean }) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      data-menu-row
      onMouseDown={(event) => event.preventDefault()}
      className={cn(
        "relative z-10 flex min-h-9 w-full items-center gap-2.5 rounded-[6px] px-2 py-1.5 text-left",
        className,
      )}
      {...props}
    />
  );
}

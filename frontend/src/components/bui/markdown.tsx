"use client";

import { cjk } from "@streamdown/cjk";
import { math } from "@streamdown/math";
import { mermaid } from "@streamdown/mermaid";
import { createContext, memo, useContext, type ComponentProps } from "react";
import type { BundledLanguage } from "shiki";
import { Streamdown } from "streamdown";

import { Pill } from "@/components/bui/button";
import { CodeBlock } from "@/components/bui/code-block";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const plugins = { cjk, math, mermaid };

const InPre = createContext(false);

function MarkdownCode({ className, children }: ComponentProps<"code">) {
  const block = useContext(InPre);
  if (!block) {
    return (
      <code
        className={cn(
          "rounded-chip bg-field px-1.5 py-0.5 font-mono text-[0.85em] text-ink shadow-hairline",
          className,
        )}
      >
        {children}
      </code>
    );
  }
  const language = /language-([\w+-]+)/.exec(className ?? "")?.[1] ?? "text";
  const code = String(children ?? "").replace(/\n$/, "");
  return (
    <CodeBlock
      code={code}
      language={language as BundledLanguage}
      filename={language}
      showLineNumbers={code.includes("\n")}
      className="my-3"
    />
  );
}

function MarkdownPre({ children }: ComponentProps<"pre">) {
  return <InPre value>{children}</InPre>;
}

const components = { code: MarkdownCode, pre: MarkdownPre };

function LinkSafetyDialog({
  isOpen,
  onClose,
  onConfirm,
  url,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  url: string;
}) {
  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Open external link?</DialogTitle>
          <DialogDescription className="break-all">{url}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Pill variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Pill>
          <Pill variant="primary" size="sm" onClick={onConfirm}>
            Open link
          </Pill>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const linkSafety = {
  enabled: true,
  renderModal: (props: {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: () => void;
    url: string;
  }) => <LinkSafetyDialog {...props} />,
};

export type MarkdownProps = ComponentProps<typeof Streamdown>;

export const Markdown = memo(
  function Markdown({ className, ...props }: MarkdownProps) {
    return (
      <Streamdown
        className={cn(
          "size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
          className,
        )}
        plugins={plugins}
        components={components}
        linkSafety={linkSafety}
        {...props}
      />
    );
  },
  (prev, next) =>
    prev.children === next.children && prev.isAnimating === next.isAnimating,
);

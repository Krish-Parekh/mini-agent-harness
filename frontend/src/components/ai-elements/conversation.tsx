"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowDownIcon } from "lucide-react";
import {
  type ComponentProps,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

const BOTTOM_THRESHOLD = 40;

type ConversationCtx = {
  scrollRef: React.RefObject<HTMLDivElement | null>;
  contentRef: React.RefObject<HTMLDivElement | null>;
  spacerHeight: number;
  isAtBottom: boolean;
  onScroll: () => void;
  scrollToBottom: (behavior?: ScrollBehavior) => void;
  scrollToTurn: (turnId: string) => void;
};

const ConversationContext = createContext<ConversationCtx | null>(null);

function useConversation() {
  const ctx = useContext(ConversationContext);
  if (!ctx) {
    throw new Error("Conversation parts must be rendered inside <Conversation>");
  }
  return ctx;
}

export type ConversationProps = ComponentProps<"div">;

export const Conversation = ({
  className,
  children,
  ...props
}: ConversationProps) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const atBottomRef = useRef(true);
  // A trailing pad sized to one viewport so a freshly anchored turn — even a
  // short one — can be scrolled all the way to the top of the visible area.
  const [spacerHeight, setSpacerHeight] = useState(0);
  const spacerRef = useRef(0);
  const setSpacer = useCallback((h: number) => {
    spacerRef.current = h;
    setSpacerHeight(h);
  }, []);

  // The real content ends one spacer above scrollHeight; park there, not in pad.
  const realBottom = (el: HTMLDivElement) =>
    Math.max(0, el.scrollHeight - spacerRef.current - el.clientHeight);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: realBottom(el), behavior });
  }, []);

  // Pin a user turn to the top of the viewport (Cursor-style). Leaving the
  // bottom-follow off here is intentional: once anchored we're no longer at the
  // bottom, so streaming output grows below without shoving the turn off-screen.
  const scrollToTurn = useCallback((turnId: string) => {
    const el = scrollRef.current;
    if (!el) return;
    const node = el.querySelector(`[data-turn-id="${turnId}"]`);
    if (!node) return;
    atBottomRef.current = false;
    setIsAtBottom(false);
    node.scrollIntoView({ block: "start", behavior: "smooth" });
  }, []);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - spacerRef.current - el.scrollTop - el.clientHeight;
    const atBottom = distance <= BOTTOM_THRESHOLD;
    atBottomRef.current = atBottom;
    setIsAtBottom(atBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el || !content) return;
    const syncSpacer = () => setSpacer(el.clientHeight);
    syncSpacer();
    el.scrollTop = el.scrollHeight;
    const observer = new ResizeObserver(() => {
      if (atBottomRef.current) el.scrollTop = realBottom(el);
    });
    observer.observe(content);
    window.addEventListener("resize", syncSpacer);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncSpacer);
    };
  }, [setSpacer]);

  return (
    <ConversationContext.Provider
      value={{
        scrollRef,
        contentRef,
        spacerHeight,
        isAtBottom,
        onScroll,
        scrollToBottom,
        scrollToTurn,
      }}
    >
      <div
        className={cn("relative flex min-h-0 flex-1 flex-col", className)}
        {...props}
      >
        {children}
      </div>
    </ConversationContext.Provider>
  );
};

export type ConversationContentProps = ComponentProps<"div">;

export const ConversationContent = ({
  className,
  children,
  ...props
}: ConversationContentProps) => {
  const { scrollRef, contentRef, spacerHeight, onScroll } = useConversation();
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      role="log"
      className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <div ref={contentRef} className={cn("p-4", className)} {...props}>
        {children}
        <div aria-hidden style={{ minHeight: spacerHeight }} />
      </div>
    </div>
  );
};

// Effect-only child: pins the latest user turn to the top when it changes.
// Rendered inside <ConversationContent> so it can reach the scroll context.
export const ConversationTurnAnchor = ({ turnId }: { turnId?: string }) => {
  const { scrollToTurn } = useConversation();
  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    // Skip the first defined value (initial load) so reopening a conversation
    // restores the bottom rather than yanking the last turn to the top.
    if (turnId && prev.current !== undefined && turnId !== prev.current) {
      scrollToTurn(turnId);
    }
    prev.current = turnId;
  }, [turnId, scrollToTurn]);
  return null;
};

export type ConversationScrollButtonProps = ComponentProps<typeof Button>;

export const ConversationScrollButton = ({
  className,
  ...props
}: ConversationScrollButtonProps) => {
  const { isAtBottom, scrollToBottom } = useConversation();
  if (isAtBottom) return null;
  return (
    <Button
      className={cn(
        "absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full",
        className,
      )}
      onClick={() => scrollToBottom()}
      size="icon"
      type="button"
      variant="outline"
      {...props}
    >
      <ArrowDownIcon className="size-4" />
    </Button>
  );
};

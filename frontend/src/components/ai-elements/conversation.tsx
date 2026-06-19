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
const USER_TURN_ANCHOR = "[data-user-turn]";
const SCROLL_DURATION_MS = 420;

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3;
}

function smoothScrollTo(
  el: HTMLDivElement,
  targetTop: number,
  onComplete?: () => void,
) {
  const start = el.scrollTop;
  const distance = targetTop - start;
  if (Math.abs(distance) < 2) {
    el.scrollTop = targetTop;
    onComplete?.();
    return () => {};
  }

  const startTime = performance.now();
  let frame = 0;
  let cancelled = false;
  const step = (now: number) => {
    if (cancelled) return;
    const progress = Math.min((now - startTime) / SCROLL_DURATION_MS, 1);
    el.scrollTop = start + distance * easeOutCubic(progress);
    if (progress < 1) {
      frame = requestAnimationFrame(step);
    } else {
      onComplete?.();
    }
  };
  frame = requestAnimationFrame(step);
  return () => {
    cancelled = true;
    cancelAnimationFrame(frame);
  };
}

function scrollNodeToContainerTop(el: HTMLDivElement, node: HTMLElement) {
  const targetScrollTop =
    node.getBoundingClientRect().top -
    el.getBoundingClientRect().top +
    el.scrollTop;
  el.scrollTop = Math.max(0, targetScrollTop);
}

type ConversationCtx = {
  scrollRef: React.RefObject<HTMLDivElement | null>;
  contentRef: React.RefObject<HTMLDivElement | null>;
  viewportHeight: number;
  isAtBottom: boolean;
  onScroll: () => void;
  scrollToBottom: (behavior?: ScrollBehavior) => void;
  scrollToUserTurn: () => void;
};

const ConversationContext = createContext<ConversationCtx | null>(null);

export function useConversation() {
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
  const [viewportHeight, setViewportHeight] = useState(0);
  const atBottomRef = useRef(true);
  const isAnimatingScrollRef = useRef(false);
  const cancelScrollRef = useRef<(() => void) | null>(null);

  const scrollBottom = (el: HTMLDivElement) =>
    Math.max(0, el.scrollHeight - el.clientHeight);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scrollRef.current;
    if (!el) return;
    cancelScrollRef.current?.();
    cancelScrollRef.current = null;
    atBottomRef.current = true;
    setIsAtBottom(true);
    const target = scrollBottom(el);
    if (behavior === "smooth") {
      isAnimatingScrollRef.current = true;
      cancelScrollRef.current = smoothScrollTo(el, target, () => {
        isAnimatingScrollRef.current = false;
        cancelScrollRef.current = null;
      });
    } else {
      el.scrollTop = target;
    }
  }, []);

  // Instant pin on send — smooth scroll from the bottom would animate through
  // every prior message one by one.
  const scrollToUserTurn = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const node = el.querySelector(USER_TURN_ANCHOR) as HTMLElement | null;
    if (!node) {
      scrollToBottom("auto");
      return;
    }
    cancelScrollRef.current?.();
    cancelScrollRef.current = null;
    isAnimatingScrollRef.current = false;
    atBottomRef.current = false;
    setIsAtBottom(false);
    scrollNodeToContainerTop(el, node);
  }, [scrollToBottom]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distance <= BOTTOM_THRESHOLD;
    atBottomRef.current = atBottom;
    setIsAtBottom(atBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el || !content) return;

    const syncViewport = () => setViewportHeight(el.clientHeight);
    syncViewport();
    el.scrollTop = el.scrollHeight;

    const observer = new ResizeObserver(() => {
      syncViewport();
      if (atBottomRef.current && !isAnimatingScrollRef.current) {
        el.scrollTop = scrollBottom(el);
      }
    });
    observer.observe(content);
    window.addEventListener("resize", syncViewport);
    return () => {
      cancelScrollRef.current?.();
      observer.disconnect();
      window.removeEventListener("resize", syncViewport);
    };
  }, []);

  return (
    <ConversationContext.Provider
      value={{
        scrollRef,
        contentRef,
        viewportHeight,
        isAtBottom,
        onScroll,
        scrollToBottom,
        scrollToUserTurn,
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
  const { scrollRef, contentRef, onScroll } = useConversation();
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      role="log"
      className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [overflow-anchor:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <div ref={contentRef} className={cn("p-4", className)} {...props}>
        {children}
      </div>
    </div>
  );
};

// After a new user turn, pin the user message to the top of the scroll area.
export const ConversationScrollAnchor = ({
  turnKey,
  optimisticTurnId,
}: {
  turnKey?: string;
  optimisticTurnId?: string;
}) => {
  const { scrollToUserTurn } = useConversation();
  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!turnKey) return;
    if (prev.current === undefined) {
      prev.current = turnKey;
      return;
    }
    if (turnKey === prev.current) return;
    if (
      optimisticTurnId &&
      prev.current === optimisticTurnId &&
      turnKey !== optimisticTurnId
    ) {
      prev.current = turnKey;
      return;
    }

    let cancelled = false;
    const frame = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!cancelled) scrollToUserTurn();
      });
    });
    prev.current = turnKey;
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
    };
  }, [turnKey, optimisticTurnId, scrollToUserTurn]);
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

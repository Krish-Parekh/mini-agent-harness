"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type AgentEvent,
  type ConversationStatus,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";

const BUSY = new Set(["running", "waiting_for_confirmation"]);

export default function ChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [status, setStatus] = useState<ConversationStatus>("idle");
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Live stream: the backend replays the full log on connect, then pushes new
  // events plus `status` updates (running / waiting / finished). Status is push,
  // not poll — we never hit the REST endpoint on a timer. Dedupe events by id so
  // replay + reconnect never double-renders.
  useEffect(() => {
    const ws = new WebSocket(api.wsUrl(id));
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.kind === "status") {
        setStatus(data.status as ConversationStatus);
        return;
      }
      const ev = data as AgentEvent;
      setEvents((prev) =>
        prev.some((e) => e.id === ev.id) ? prev : [...prev, ev],
      );
    };
    return () => ws.close();
  }, [id]);

  const busy = BUSY.has(status);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const waiting = status === "waiting_for_confirmation";

  const pendingAction = useMemo(() => {
    const observed = new Set(
      events.filter((e) => e.kind === "observation").map((e) => e.tool_call_id),
    );
    return [...events]
      .reverse()
      .find((e) => e.kind === "action" && !observed.has(e.tool_call_id));
  }, [events]);

  async function send(message: PromptInputMessage) {
    const text = message.text.trim();
    if (!text || busy) return;
    setInput("");
    setStatus("running"); // optimistic; the socket confirms and later settles it
    try {
      await api.sendMessage(id, text);
    } catch {
      setInput(text);
      setStatus("idle");
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col p-4">
      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {events.length === 0 && (
          <p className="text-muted-foreground py-8 text-center text-sm">
            Preparing workspace…
          </p>
        )}
        {events.map((ev) => (
          <EventBubble key={ev.id} ev={ev} />
        ))}
        <div ref={bottomRef} />
      </div>

      {waiting && pendingAction && (
        <ConfirmBar
          action={pendingAction}
          onApprove={() => {
            setStatus("running");
            api.confirm(id, true).catch(() => {});
          }}
          onReject={() => {
            setStatus("running");
            api.confirm(id, false).catch(() => {});
          }}
        />
      )}

      <PromptInput onSubmit={send} className="mt-3">
        <PromptInputBody>
          <PromptInputTextarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              waiting ? "Approve or reject the action above…" : "Send a message…"
            }
            disabled={busy}
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools />
          <PromptInputSubmit
            status={status === "error" ? "error" : busy ? "submitted" : undefined}
            disabled={busy || !input.trim()}
          />
        </PromptInputFooter>
      </PromptInput>
    </main>
  );
}

function ConfirmBar({
  action,
  onApprove,
  onReject,
}: {
  action: AgentEvent;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="border-destructive/40 bg-destructive/5 mt-3 rounded-md border p-3">
      <p className="text-sm font-medium">Approval needed</p>
      <pre className="text-muted-foreground mt-1 overflow-x-auto text-xs">
        {action.tool_name}: {JSON.stringify(action.arguments)}
      </pre>
      <div className="mt-2 flex gap-2">
        <Button size="sm" onClick={onApprove}>
          Approve
        </Button>
        <Button size="sm" variant="destructive" onClick={onReject}>
          Reject
        </Button>
      </div>
    </div>
  );
}

function EventBubble({ ev }: { ev: AgentEvent }) {
  if (ev.kind === "message" && ev.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-primary text-primary-foreground max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
          {ev.text}
        </div>
      </div>
    );
  }
  if (ev.kind === "message" && ev.role === "assistant") {
    return (
      <div className="flex justify-start">
        <div className="bg-muted max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
          {ev.text}
        </div>
      </div>
    );
  }
  if (ev.kind === "message") {
    // system note (e.g. workspace ready)
    return (
      <p className="text-muted-foreground text-center text-xs">{ev.text}</p>
    );
  }
  if (ev.kind === "action") {
    return (
      <div className="text-muted-foreground rounded-md border px-3 py-2 text-xs">
        <span className="font-medium">🔧 {ev.tool_name}</span>
        <pre className="mt-1 overflow-x-auto">
          {JSON.stringify(ev.arguments, null, 2)}
        </pre>
      </div>
    );
  }
  if (ev.kind === "observation") {
    return (
      <pre
        className={`overflow-x-auto rounded-md border px-3 py-2 text-xs ${
          ev.error ? "border-destructive/40 text-destructive" : "text-muted-foreground"
        }`}
      >
        {(ev.content ?? "").slice(0, 4000)}
      </pre>
    );
  }
  if (ev.kind === "error") {
    return <p className="text-destructive text-sm">⚠ {ev.message}</p>;
  }
  return null;
}

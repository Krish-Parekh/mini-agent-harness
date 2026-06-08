"use client";

import { use, useEffect, useMemo, useState } from "react";

import {
  api,
  type AgentEvent,
  type ConversationStatus,
} from "@/lib/api";
import { EventRow } from "@/components/conversation-stream";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import { CheckIcon } from "lucide-react";

const BUSY = new Set(["running", "waiting_for_confirmation"]);

// First entry is the default and matches the backend config default.
const MODELS = [
  { id: "gpt-4o-mini", name: "GPT-4o mini" },
  { id: "gpt-4o", name: "GPT-4o" },
  { id: "gpt-4.1", name: "GPT-4.1" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 mini" },
];

export default function ChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [status, setStatus] = useState<ConversationStatus>("idle");
  const [input, setInput] = useState("");
  const [model, setModel] = useState(MODELS[0].id);
  const [modelOpen, setModelOpen] = useState(false);
  const selectedModel = MODELS.find((m) => m.id === model);

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

  const waiting = status === "waiting_for_confirmation";

  const observationByCall = useMemo(() => {
    const map = new Map<string, AgentEvent>();
    for (const e of events) {
      if (e.kind === "observation" && e.tool_call_id) map.set(e.tool_call_id, e);
    }
    return map;
  }, [events]);

  // Newest action with no observation yet — only the approval target while
  // status is waiting (see call site); mid-run it's the executing action.
  const lastUnresolvedAction = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (
        e.kind === "action" &&
        e.tool_call_id &&
        !observationByCall.has(e.tool_call_id)
      ) {
        return e;
      }
    }
    return undefined;
  }, [events, observationByCall]);

  async function send(message: PromptInputMessage) {
    const text = message.text.trim();
    if (!text || busy) return;
    setInput("");
    setStatus("running"); // optimistic; the socket confirms and later settles it
    try {
      await api.sendMessage(id, text, model);
    } catch {
      setInput(text);
      setStatus("idle");
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col p-4">
      <Conversation>
        <ConversationContent className="space-y-3 px-0">
          {events.length === 0 && (
            <p className="text-muted-foreground py-8 text-center text-sm">
              Preparing workspace…
            </p>
          )}
          {events.map((ev) => (
            <EventRow
              key={ev.id}
              ev={ev}
              observation={
                ev.kind === "action" && ev.tool_call_id
                  ? observationByCall.get(ev.tool_call_id)
                  : undefined
              }
              pending={waiting && ev.id === lastUnresolvedAction?.id}
              onApprove={() => {
                setStatus("running");
                api.confirm(id, true).catch(() => {});
              }}
              onReject={() => {
                setStatus("running");
                api.confirm(id, false).catch(() => {});
              }}
            />
          ))}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

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
          <PromptInputTools>
            <ModelSelector open={modelOpen} onOpenChange={setModelOpen}>
              <ModelSelectorTrigger
                render={
                  <PromptInputButton>
                    <ModelSelectorLogo provider="openai" />
                    <ModelSelectorName>
                      {selectedModel?.name ?? "Model"}
                    </ModelSelectorName>
                  </PromptInputButton>
                }
              />
              <ModelSelectorContent className="[&_[data-slot=dialog-close]]:top-2.5 [&_[data-slot=dialog-close]]:right-2.5 [&_[data-slot=command-input-wrapper]]:pr-12">
                <ModelSelectorInput placeholder="Search models…" />
                <ModelSelectorList>
                  <ModelSelectorEmpty>No models found.</ModelSelectorEmpty>
                  <ModelSelectorGroup heading="OpenAI">
                    {MODELS.map((m) => (
                      <ModelSelectorItem
                        key={m.id}
                        value={m.id}
                        onSelect={() => {
                          setModel(m.id);
                          setModelOpen(false);
                        }}
                      >
                        <ModelSelectorLogo provider="openai" />
                        <ModelSelectorName>{m.name}</ModelSelectorName>
                        {model === m.id ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </ModelSelectorItem>
                    ))}
                  </ModelSelectorGroup>
                </ModelSelectorList>
              </ModelSelectorContent>
            </ModelSelector>
          </PromptInputTools>
          <PromptInputSubmit
            status={status === "error" ? "error" : busy ? "submitted" : undefined}
            disabled={busy || !input.trim()}
          />
        </PromptInputFooter>
      </PromptInput>
    </main>
  );
}

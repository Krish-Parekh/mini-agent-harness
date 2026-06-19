"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  api,
  ApiError,
  type AgentEvent,
  type ChangedFile,
  type ConversationStatus,
  type PlanStep,
  type StepStatus,
} from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { useConversation } from "@/lib/queries";

const BUSY = new Set<ConversationStatus>([
  "running",
  "waiting_for_confirmation",
]);

/**
 * Owns a conversation's live state: the event websocket (connect, reconnect,
 * dedupe), run status, changed files, and everything derivable from the event
 * log. Pages consume this and stay presentational.
 */
export function useConversationStream(id: string) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  // Only set by the websocket (status seed on connect + live updates). Until
  // it arrives we fall back to the REST status below, so the chat opens in its
  // real state instead of a stale "idle".
  const [wsStatus, setStatus] = useState<ConversationStatus | null>(null);
  const [changes, setChanges] = useState<ChangedFile[]>([]);
  const [wsGone, setWsGone] = useState(false);
  const [connected, setConnected] = useState(false);
  const stopping = useRef(false);

  const { data: conversation, error } = useConversation(id);
  const exists = !!conversation;
  const missing = wsGone || (error instanceof ApiError && error.status === 404);

  useEffect(() => {
    if (!exists) return;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let unmounted = false;

    function connect() {
      ws = new WebSocket(api.wsUrl(id));
      ws.onopen = () => setConnected(true);
      ws.onmessage = (msg) => {
        let data;
        try {
          data = JSON.parse(msg.data);
        } catch {
          // One malformed frame must not take the socket down with it.
          console.warn("Dropped malformed websocket frame", msg.data);
          return;
        }
        if (data.kind === "status") {
          const next = data.status as ConversationStatus;
          setStatus(next);
          // A stop settled: the backend trimmed the cancelled turn, so resync.
          if (stopping.current && !BUSY.has(next)) {
            stopping.current = false;
            api
              .events(id)
              .then(setEvents)
              .catch((e) =>
                toast.error(messageFor(e), { id: "resync-events" }),
              );
          }
          return;
        }
        const ev = data as AgentEvent;
        setEvents((prev) =>
          prev.some((e) => e.id === ev.id) ? prev : [...prev, ev],
        );
      };
      ws.onclose = (e) => {
        setConnected(false);
        // 4404: deleted mid-session. Stop reconnecting and fall through to the
        // not-found screen rather than looping against a gone conversation.
        if (e.code === 4404) {
          setWsGone(true);
          return;
        }
        if (unmounted) return;
        reconnectTimer = setTimeout(connect, 1000);
      };
    }
    connect();

    return () => {
      unmounted = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [id, exists]);

  const status: ConversationStatus = wsStatus ?? conversation?.status ?? "idle";
  const busy = BUSY.has(status);
  const waiting = status === "waiting_for_confirmation";

  const observationByCall = useMemo(() => {
    const map = new Map<string, AgentEvent>();
    for (const e of events) {
      if (e.kind === "observation" && e.tool_call_id) map.set(e.tool_call_id, e);
    }
    return map;
  }, [events]);

  const refreshChanges = useCallback(() => {
    api
      .changes(id)
      .then(setChanges)
      // Keyed toast: a flapping backend yields one toast, not one per retry.
      .catch((e) => toast.error(messageFor(e), { id: "refresh-changes" }));
  }, [id]);

  // Git is the source of truth for changed files; refetch whenever a tool
  // finishes (each observation), since bash can touch files too.
  useEffect(() => {
    refreshChanges();
  }, [refreshChanges, observationByCall.size]);

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

  // The agent's last `ask_user` that the user hasn't replied to yet.
  const pendingQuestion = useMemo(() => {
    let candidate: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "ask_user") candidate = e;
      else if (e.kind === "message" && e.role === "user") candidate = undefined;
    }
    return candidate;
  }, [events]);

  // The agent's last presented plan that the user hasn't responded to yet.
  const pendingPlan = useMemo(() => {
    let candidate: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "present_plan") candidate = e;
      else if (e.kind === "message" && e.role === "user") candidate = undefined;
    }
    return candidate;
  }, [events]);

  const lastUserTurnId = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.kind === "message" && e.role === "user") return e.id;
    }
    return undefined;
  }, [events]);

  // Live statuses for the latest plan's steps: seeded from its `present_plan`
  // arguments, then folded forward with each `update_plan` call. Replayed
  // events on reconnect rebuild the same state, so this survives refresh.
  const livePlan = useMemo(() => {
    let planEvent: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "present_plan") planEvent = e;
    }
    if (!planEvent) return undefined;
    const steps = ((planEvent.arguments?.steps as PlanStep[]) ?? []).map(
      (s) => ({ ...s }),
    );
    let afterPlan = false;
    for (const e of events) {
      if (e === planEvent) {
        afterPlan = true;
        continue;
      }
      if (!afterPlan || e.kind !== "action" || e.tool_name !== "update_plan")
        continue;
      const step = Number(e.arguments?.step);
      if (step >= 1 && step <= steps.length)
        steps[step - 1].status = e.arguments?.status as StepStatus;
    }
    return { planId: planEvent.id, steps };
  }, [events]);

  const stop = useCallback(() => {
    if (!BUSY.has(status)) return;
    stopping.current = true;
    api.stop(id).catch((e) => {
      stopping.current = false;
      toast.error(messageFor(e));
    });
  }, [id, status]);

  return {
    conversation,
    exists,
    missing,
    connected,
    events,
    status,
    setStatus,
    busy,
    waiting,
    changes,
    refreshChanges,
    observationByCall,
    lastUnresolvedAction,
    pendingQuestion,
    pendingPlan,
    livePlan,
    lastUserTurnId,
    stop,
  };
}

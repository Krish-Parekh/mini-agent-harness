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

export function useConversationStream(id: string) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
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
    let authFailures = 0;

    async function connect() {
      const protocols = await api.wsProtocols();
      if (unmounted) return;
      ws = new WebSocket(api.wsUrl(id), protocols);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (msg) => {
        let data;
        try {
          data = JSON.parse(msg.data);
        } catch {
          console.warn("Dropped malformed websocket frame", msg.data);
          return;
        }
        if (data.kind === "status") {
          const next = data.status as ConversationStatus;
          setStatus(next);
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
        if (e.code === 4404) {
          setWsGone(true);
          return;
        }
        if (e.code === 4401 && ++authFailures > 2) return;
        if (unmounted) return;
        reconnectTimer = setTimeout(() => void connect(), 1000);
      };
    }
    void connect();

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
      .catch((e) => toast.error(messageFor(e), { id: "refresh-changes" }));
  }, [id]);

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

  const pendingQuestion = useMemo(() => {
    let candidate: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "ask_user") candidate = e;
      else if (e.kind === "message" && e.role === "user") candidate = undefined;
    }
    return candidate;
  }, [events]);

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

"use client";

import { useEffect } from "react";

import { api, ApiError } from "@/lib/api";
import { conversationsCollection } from "@/lib/collections";

export function useConversationChanges() {
  useEffect(() => {
    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connectedBefore = false;

    const refetch = () => void conversationsCollection.utils.refetch().catch(() => {});

    async function connect() {
      if (connectedBefore) refetch();
      connectedBefore = true;
      try {
        for await (const frame of api.changesStream(controller.signal)) {
          if (frame.event === "changed") refetch();
        }
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) return;
      }
      if (controller.signal.aborted) return;
      reconnectTimer = setTimeout(() => void connect(), 2000);
    }
    void connect();

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      controller.abort();
    };
  }, []);
}

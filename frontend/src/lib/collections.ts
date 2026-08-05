import { createCollection, createOptimisticAction } from "@tanstack/react-db";
import { queryCollectionOptions } from "@tanstack/query-db-collection";

import { api, type AgentEvent, type ConversationInfo } from "@/lib/api";
import { queryClient } from "@/lib/query-client";

export const conversationsCollection = createCollection(
  queryCollectionOptions({
    queryClient,
    queryKey: ["conversations"],
    queryFn: () => api.conversations(),
    getKey: (c: ConversationInfo) => c.id,
    onDelete: async ({ transaction }) => {
      await Promise.all(
        transaction.mutations.map((m) => api.deleteConversation(String(m.key))),
      );
      return { refetch: false };
    },
  }),
);

export async function createConversation(body: {
  repo: string;
  branch?: string | null;
}): Promise<ConversationInfo> {
  const conversation = await api.createConversation(body);
  conversationsCollection.utils.writeUpsert(conversation);
  return conversation;
}

const eventCollections = new Map<
  string,
  ReturnType<typeof createEventsCollection>
>();

function createEventsCollection(conversationId: string) {
  return createCollection(
    queryCollectionOptions({
      queryClient,
      queryKey: ["events", conversationId],
      queryFn: () => api.events(conversationId),
      getKey: (e: AgentEvent) => e.client_event_id ?? e.id,
    }),
  );
}

export function eventsCollection(conversationId: string) {
  let collection = eventCollections.get(conversationId);
  if (!collection) {
    collection = createEventsCollection(conversationId);
    eventCollections.set(conversationId, collection);
  }
  return collection;
}

export type SendMessageVars = {
  conversationId: string;
  clientEventId: string;
  text: string;
  model?: string;
};

export const sendMessage = createOptimisticAction<SendMessageVars>({
  onMutate: ({ conversationId, clientEventId, text }) => {
    eventsCollection(conversationId).insert({
      id: clientEventId,
      client_event_id: clientEventId,
      timestamp: Date.now() / 1000,
      source: "user",
      kind: "message",
      role: "user",
      text,
    });
  },
  mutationFn: async ({ conversationId, clientEventId, text, model }) => {
    await api.sendMessage(conversationId, text, model, clientEventId);
  },
});

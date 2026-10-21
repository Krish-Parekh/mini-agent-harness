import { createCollection, createOptimisticAction } from "@tanstack/react-db";
import { queryCollectionOptions } from "@tanstack/query-db-collection";

import {
  api,
  type AttachmentRef,
  type ConversationInfo,
  type CreateConversationBody,
} from "@/lib/api";
import { eventKey } from "@/lib/events";
import { queryClient } from "@/lib/query-client";

export const conversationsCollection = createCollection(
  queryCollectionOptions({
    queryClient,
    queryKey: ["conversations"],
    queryFn: () => api.conversations(),
    getKey: (c: ConversationInfo) => c.id,
    refetchInterval: 5000,
    onDelete: async ({ transaction }) => {
      await Promise.all(
        transaction.mutations.map((m) => api.deleteConversation(String(m.key))),
      );
      return { refetch: false };
    },
  }),
);

export async function createConversation(
  body: CreateConversationBody,
): Promise<ConversationInfo> {
  const conversation = await api.createConversation(body);
  try {
    if (conversationsCollection.isReady()) {
      conversationsCollection.utils.writeUpsert(conversation);
    }
  } catch {}
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
      getKey: eventKey,
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
  attachments: AttachmentRef[];
};

export const sendMessage = createOptimisticAction<SendMessageVars>({
  onMutate: ({ conversationId, clientEventId, text, attachments }) => {
    eventsCollection(conversationId).insert({
      id: clientEventId,
      client_event_id: clientEventId,
      timestamp: Date.now() / 1000,
      source: "user",
      kind: "message",
      role: "user",
      text,
      attachments,
    });
  },
  mutationFn: async ({ conversationId, clientEventId, text, model, attachments }) => {
    const events = eventsCollection(conversationId);
    const row = events.isReady() ? events.get(clientEventId) : undefined;
    if (row) events.utils.writeUpsert(row);
    try {
      await api.sendMessage(conversationId, text, model, clientEventId, attachments);
    } catch (e) {
      if (row) events.utils.writeDelete(clientEventId);
      throw e;
    }
  },
});

import { useLiveQuery } from "@tanstack/react-db";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";
import { toast } from "sonner";

import {
  api,
  ApiError,
  type AttachmentRef,
  type Branch,
  type ConversationContext,
  type ConversationInfo,
  type CreateConversationBody,
  type McpConnection,
  type Repo,
  type Memory,
  type SandboxProvider,
  type TurnInfo,
  type Skill,
} from "@/lib/api";
import { signedAttachmentUrl } from "@/lib/attachments";
import { conversationsCollection, createConversation } from "@/lib/collections";
import { messageFor } from "@/lib/errors";

export const queryKeys = {
  repos: ["repos"] as const,
  branches: (repo: string) => ["branches", repo] as const,
  sandboxProviders: ["sandbox-providers"] as const,
  skills: ["skills"] as const,
  memories: ["memories"] as const,
  mcpConnections: ["mcp-connections"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  context: (id: string) => ["context", id] as const,
  events: (id: string) => ["events", id] as const,
  files: (id: string) => ["files", id] as const,
  turns: (id: string) => ["turns", id] as const,
};

export function useRepos(enabled = true) {
  return useQuery<Repo[]>({
    queryKey: queryKeys.repos,
    queryFn: api.repos,
    enabled,
  });
}

export function useBranches(repo: string | null) {
  return useQuery<Branch[]>({
    queryKey: queryKeys.branches(repo ?? ""),
    queryFn: () => api.branches(repo!),
    enabled: !!repo,
  });
}

export function useSandboxProviders() {
  return useQuery<SandboxProvider[]>({
    queryKey: queryKeys.sandboxProviders,
    queryFn: api.sandboxProviders,
    staleTime: 60_000,
  });
}

export function useSkills(enabled = true) {
  return useQuery<Skill[]>({
    queryKey: queryKeys.skills,
    queryFn: api.skills,
    enabled,
  });
}

export function useAttachmentUrl(attachment: AttachmentRef) {
  return useQuery<string>({
    queryKey: ["attachment-url", attachment.path],
    queryFn: () => signedAttachmentUrl(attachment),
    staleTime: 50 * 60_000,
  });
}

export function useTurns(id: string, status: string | undefined) {
  return useQuery<TurnInfo[]>({
    queryKey: [...queryKeys.turns(id), status],
    queryFn: () => api.turns(id),
    enabled: status !== undefined && status !== "running",
  });
}

export function useMemories() {
  return useQuery<Memory[]>({
    queryKey: queryKeys.memories,
    queryFn: api.memories,
  });
}

export function useMcpConnections() {
  return useQuery<McpConnection[]>({
    queryKey: queryKeys.mcpConnections,
    queryFn: api.mcpConnections,
  });
}

export function useImportRepo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (repo: string) => api.importRepo(repo),
    onSuccess: (repo) => {
      queryClient.setQueryData<Repo[]>(queryKeys.repos, (prev) =>
        !prev || prev.some((r) => r.full_name === repo.full_name)
          ? prev
          : [repo, ...prev],
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.repos });
    },
  });
}

function byUpdatedDesc(a: ConversationInfo, b: ConversationInfo) {
  return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
}

function refetchConversations() {
  return conversationsCollection.utils.refetch();
}

export function useConversations() {
  const { data, isLoading, status } = useLiveQuery(
    () => conversationsCollection,
  );
  const sorted = useMemo(
    () => (data ? [...data].sort(byUpdatedDesc) : undefined),
    [data],
  );
  return {
    data: sorted,
    isPending: isLoading,
    isError: status === "error",
    refetch: refetchConversations,
  };
}

export function useConversation(id: string) {
  return useQuery<ConversationInfo>({
    queryKey: queryKeys.conversation(id),
    queryFn: () => api.conversation(id),
    retry: (count, err) =>
      !(err instanceof ApiError && err.status === 404) && count < 3,
  });
}

export function useDeleteConversation() {
  const router = useRouter();
  const pathname = usePathname();
  return useMutation({
    mutationFn: async (id: string) => {
      await conversationsCollection.delete(id).isPersisted.promise;
      return id;
    },
    onSuccess: (id) => {
      if (pathname === `/chat/${id}`) router.push("/");
    },
    onError: (e) => toast.error(messageFor(e)),
  });
}

export function useStartChat() {
  const router = useRouter();
  return useMutation({
    mutationFn: (body: CreateConversationBody) => createConversation(body),
    onSuccess: (conversation) => router.push(`/chat/${conversation.id}`),
    onError: (e) => toast.error(messageFor(e)),
  });
}

export function useConversationContext(id: string, enabled = true) {
  return useQuery<ConversationContext>({
    queryKey: queryKeys.context(id),
    queryFn: () => api.context(id),
    enabled,
  });
}

export function useFiles(id: string, enabled = true) {
  return useQuery<string[]>({
    queryKey: queryKeys.files(id),
    queryFn: () => api.files(id),
    enabled,
  });
}


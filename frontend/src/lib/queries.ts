import { useLiveQuery } from "@tanstack/react-db";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";

import { api, ApiError, type ConversationInfo, type Repo } from "@/lib/api";
import { conversationsCollection, createConversation } from "@/lib/collections";
import { messageFor } from "@/lib/errors";

export const queryKeys = {
  repos: ["repos"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  events: (id: string) => ["events", id] as const,
  files: (id: string) => ["files", id] as const,
};

export function useRepos(enabled = true) {
  return useQuery<Repo[]>({
    queryKey: queryKeys.repos,
    queryFn: api.repos,
    enabled,
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

export function useConversations() {
  const { data, isLoading, status } = useLiveQuery(
    () => conversationsCollection,
  );
  const sorted = data
    ? [...data].sort((a, b) =>
        (b.updated_at ?? "").localeCompare(a.updated_at ?? ""),
      )
    : undefined;
  return {
    data: sorted,
    isPending: isLoading,
    isError: status === "error",
    refetch: () => conversationsCollection.utils.refetch(),
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
    mutationFn: (source: Repo | { repo: string; branch: string | null }) => {
      const body =
        "full_name" in source
          ? { repo: source.full_name, branch: source.default_branch }
          : { repo: source.repo, branch: source.branch };
      return createConversation(body);
    },
    onSuccess: (conversation) => router.push(`/chat/${conversation.id}`),
    onError: (e) => toast.error(messageFor(e)),
  });
}

export function useFiles(id: string, enabled = true) {
  return useQuery<string[]>({
    queryKey: queryKeys.files(id),
    queryFn: () => api.files(id),
    enabled,
  });
}


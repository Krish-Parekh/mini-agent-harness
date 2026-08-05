import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";

import { api, ApiError, type ConversationInfo, type Repo } from "@/lib/api";

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
  return useQuery<ConversationInfo[]>({
    queryKey: queryKeys.conversations,
    queryFn: api.conversations,
  });
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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_, id) => {
      queryClient.setQueryData<ConversationInfo[]>(
        queryKeys.conversations,
        (prev) => prev?.filter((c) => c.id !== id),
      );
      if (pathname === `/chat/${id}`) router.push("/");
    },
  });
}

export function useStartChat() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (source: Repo | { repo: string; branch: string | null }) => {
      const body =
        "full_name" in source
          ? { repo: source.full_name, branch: source.default_branch }
          : { repo: source.repo, branch: source.branch };
      return api.createConversation(body);
    },
    onSuccess: (conversation) => {
      queryClient.setQueryData<ConversationInfo[]>(
        queryKeys.conversations,
        (prev) => [conversation, ...(prev ?? [])],
      );
      router.push(`/chat/${conversation.id}`);
    },
  });
}

export function useFiles(id: string, enabled = true) {
  return useQuery<string[]>({
    queryKey: queryKeys.files(id),
    queryFn: () => api.files(id),
    enabled,
  });
}


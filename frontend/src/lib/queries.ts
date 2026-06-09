import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";

import {
  api,
  ApiError,
  type ConversationInfo,
  type GitHubStatus,
  type Lane,
  type Repo,
} from "@/lib/api";

export const queryKeys = {
  githubStatus: ["github", "status"] as const,
  repos: ["repos"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  events: (id: string) => ["events", id] as const,
};

export function useGitHubStatus() {
  return useQuery<GitHubStatus>({
    queryKey: queryKeys.githubStatus,
    queryFn: api.githubStatus,
  });
}

export function useRepos(enabled = true) {
  return useQuery<Repo[]>({
    queryKey: queryKeys.repos,
    queryFn: api.repos,
    enabled,
  });
}

export function useDisconnect() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      // Reflect the signed-out state immediately, drop the now-stale repo list,
      // and send the user back to the connect screen.
      queryClient.setQueryData<GitHubStatus>(queryKeys.githubStatus, {
        connected: false,
        login: null,
      });
      queryClient.removeQueries({ queryKey: queryKeys.repos });
      router.push("/");
    },
  });
}

export function useImportRepo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (repo: string) => api.importRepo(repo),
    onSuccess: (repo) => {
      // Show the fork right away, then refetch for canonical ordering/fields.
      queryClient.setQueryData<Repo[]>(queryKeys.repos, (prev) =>
        !prev || prev.some((r) => r.full_name === repo.full_name)
          ? prev
          : [repo, ...prev],
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.repos });
    },
  });
}

export function useConversations(options?: { refetchInterval?: number }) {
  return useQuery<ConversationInfo[]>({
    queryKey: queryKeys.conversations,
    queryFn: api.conversations,
    refetchInterval: options?.refetchInterval,
  });
}

// Existence + metadata for a single conversation. This is the source of truth
// for "does this conversation exist" — the chat page gates its event socket on
// it. A 404 is terminal (the conversation is gone), so don't retry it.
export function useConversation(id: string) {
  return useQuery<ConversationInfo>({
    queryKey: queryKeys.conversation(id),
    queryFn: () => api.conversation(id),
    retry: (count, err) =>
      !(err instanceof ApiError && err.status === 404) && count < 3,
  });
}

export function useSetLane() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, lane }: { id: string; lane: Lane }) =>
      api.setLane(id, lane),
    // Move the card to its new lane instantly; reconcile on settle.
    onMutate: async ({ id, lane }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.conversations });
      const prev = queryClient.getQueryData<ConversationInfo[]>(
        queryKeys.conversations,
      );
      queryClient.setQueryData<ConversationInfo[]>(
        queryKeys.conversations,
        (cs) => cs?.map((c) => (c.id === id ? { ...c, lane } : c)),
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(queryKeys.conversations, ctx.prev);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    },
  });
}

export function useDeleteConversation() {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_, id) => {
      // Drop it from the sidebar immediately, then refetch for canonical state.
      queryClient.setQueryData<ConversationInfo[]>(
        queryKeys.conversations,
        (prev) => prev?.filter((c) => c.id !== id),
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      // If we were viewing the chat we just deleted, leave its dead page.
      if (pathname === `/chat/${id}`) router.push("/");
    },
  });
}

export function useStartChat() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useMutation({
    // Accepts a full Repo (home/repo picker) or a bare repo+branch pair (the
    // sidebar's "new chat in the same repo", which only has those two fields).
    mutationFn: (source: Repo | { repo: string; branch: string | null }) => {
      const body =
        "full_name" in source
          ? { repo: source.full_name, branch: source.default_branch }
          : { repo: source.repo, branch: source.branch };
      return api.createConversation(body);
    },
    onSuccess: (conversation) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      router.push(`/chat/${conversation.id}`);
    },
  });
}

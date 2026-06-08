import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";

import {
  api,
  type ConversationInfo,
  type GitHubStatus,
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

export function useConversations() {
  return useQuery<ConversationInfo[]>({
    queryKey: queryKeys.conversations,
    queryFn: api.conversations,
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
    mutationFn: (repo: Repo) =>
      api.createConversation({
        repo: repo.full_name,
        branch: repo.default_branch,
      }),
    onSuccess: (conversation) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      router.push(`/chat/${conversation.id}`);
    },
  });
}

"use client";

import {
  ArrowRight01Icon,
  Delete02Icon,
  Folder01Icon,
  MoreHorizontalIcon,
  PencilEdit02Icon,
  Settings01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/app/providers";
import { GettingStarted } from "@/components/getting-started";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { type ConversationInfo } from "@/lib/api";
import {
  requestComposerFocus,
  setComposerSelection,
} from "@/lib/composer-selection";
import { useConversations, useDeleteConversation } from "@/lib/queries";

const NO_REPO = "No repository";

function conversationLabel(c: ConversationInfo): string {
  const name = c.repo?.split("/").pop();
  if (name && c.title?.startsWith(`${name}: `)) {
    return c.title.slice(name.length + 2);
  }
  return c.title ?? `Chat ${c.id.slice(0, 6)}`;
}

function groupByRepo(items: ConversationInfo[]) {
  const byRepo = new Map<string, ConversationInfo[]>();
  for (const c of items) {
    const key = c.repo ?? NO_REPO;
    byRepo.set(key, [...(byRepo.get(key) ?? []), c]);
  }
  return [...byRepo].map(([repo, chats]) => ({
    repo,
    chats: chats.sort((a, b) =>
      (b.created_at ?? "").localeCompare(a.created_at ?? ""),
    ),
  }));
}

function StatusDot({ status }: { status: ConversationInfo["status"] }) {
  if (status === "running") return <Spinner className="size-3 shrink-0" />;
  if (status === "waiting_for_confirmation") {
    return (
      <span
        aria-label="Waiting for you"
        className="size-2 shrink-0 rounded-full bg-amber-500"
      />
    );
  }
  return null;
}

function ChatRow({
  c,
  isActive,
  onDelete,
  onNavigate,
  deleting,
}: {
  c: ConversationInfo;
  isActive: boolean;
  onDelete: () => void;
  onNavigate: () => void;
  deleting: boolean;
}) {
  return (
    <SidebarMenuSubItem>
      <SidebarMenuSubButton
        isActive={isActive}
        render={<Link href={`/chat/${c.id}`} onClick={onNavigate} />}
        className="pr-7"
      >
        <span className="truncate">{conversationLabel(c)}</span>
        <span className="ml-auto flex items-center">
          <StatusDot status={c.status} />
        </span>
      </SidebarMenuSubButton>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Chat options"
          className="absolute top-1 right-1 flex size-5 items-center justify-center rounded-md text-sidebar-foreground opacity-0 group-hover/menu-sub-item:opacity-100 hover:bg-sidebar-accent focus-visible:opacity-100 data-popup-open:opacity-100"
        >
          <HugeiconsIcon icon={MoreHorizontalIcon} className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start">
          <DropdownMenuItem
            variant="destructive"
            disabled={deleting}
            onClick={onDelete}
          >
            <HugeiconsIcon icon={Delete02Icon} />
            Delete chat
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuSubItem>
  );
}

function RepoFolder({
  repo,
  chats,
  open,
  onOpenChange,
  activeId,
}: {
  repo: string;
  chats: ConversationInfo[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeId: string | null;
}) {
  const deleteConversation = useDeleteConversation();
  const { isMobile, setOpenMobile } = useSidebar();
  const name = repo === NO_REPO ? repo : repo.split("/").pop();

  return (
    <Collapsible
      open={open}
      onOpenChange={onOpenChange}
      render={<SidebarMenuItem />}
    >
      <CollapsibleTrigger
        render={<SidebarMenuButton tooltip={repo} className="group/folder" />}
      >
        <HugeiconsIcon icon={Folder01Icon} />
        <span className="truncate">{name}</span>
        <HugeiconsIcon
          icon={ArrowRight01Icon}
          className="ml-auto transition-transform group-data-panel-open/folder:rotate-90"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <SidebarMenuSub>
          {chats.map((c) => (
            <ChatRow
              key={c.id}
              c={c}
              isActive={c.id === activeId}
              deleting={deleteConversation.isPending}
              onDelete={() => deleteConversation.mutate(c.id)}
              onNavigate={() => isMobile && setOpenMobile(false)}
            />
          ))}
        </SidebarMenuSub>
      </CollapsibleContent>
    </Collapsible>
  );
}

function RepoFolders({ activeId }: { activeId: string | null }) {
  const { data, isPending, isError, refetch } = useConversations();
  const active = activeId ? data?.find((c) => c.id === activeId) : undefined;
  const [openRepos, setOpenRepos] = useState<Set<string>>(new Set());
  const [lastActive, setLastActive] = useState<string | null>(null);
  if (active && active.id !== lastActive) {
    setLastActive(active.id);
    setOpenRepos((prev) => new Set(prev).add(active.repo ?? NO_REPO));
  }

  function setOpen(repo: string, open: boolean) {
    setOpenRepos((prev) => {
      const next = new Set(prev);
      if (open) next.add(repo);
      else next.delete(repo);
      return next;
    });
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Repos</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {isPending &&
            ["70%", "55%", "80%"].map((w, i) => (
              <SidebarMenuSkeleton key={i} showIcon width={w} />
            ))}
          {isError && (
            <div className="flex flex-col items-start gap-1 px-2 py-1.5 text-sm text-muted-foreground">
              Couldn&apos;t load chats.
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => refetch()}
              >
                Retry
              </Button>
            </div>
          )}
          {data?.length === 0 && (
            <p className="px-2 py-1.5 text-sm text-muted-foreground">
              No chats yet.
            </p>
          )}
          {data &&
            groupByRepo(data).map(({ repo, chats }) => (
              <RepoFolder
                key={repo}
                repo={repo}
                chats={chats}
                open={openRepos.has(repo)}
                onOpenChange={(open) => setOpen(repo, open)}
                activeId={activeId}
              />
            ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

export function AccountFooter() {
  const { auth } = useAuth();
  if (!auth) return null;

  const label = auth.github.login ?? auth.user.email ?? "Account";
  const avatar = auth.github.avatar_url ?? auth.user.avatar_url;

  return (
    <SidebarMenu>
      <SidebarMenuItem className="flex items-center gap-1">
        <div className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5">
          <Avatar className="size-6">
            <AvatarImage src={avatar ?? undefined} alt={label} />
            <AvatarFallback className="text-[10px]">
              {label.slice(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="truncate text-sm font-medium">{label}</span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Settings"
          nativeButton={false}
          render={<Link href="/settings" />}
        >
          <HugeiconsIcon icon={Settings01Icon} />
        </Button>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const { data } = useConversations();
  const { isMobile, setOpenMobile } = useSidebar();
  const activeId = pathname.startsWith("/chat/")
    ? pathname.slice("/chat/".length)
    : null;
  const activeConv = activeId ? data?.find((c) => c.id === activeId) : undefined;

  function closeOnMobile() {
    if (isMobile) setOpenMobile(false);
  }

  function newChat() {
    if (activeConv?.repo) {
      setComposerSelection({ repo: activeConv.repo, branch: activeConv.branch });
    }
    requestComposerFocus();
    closeOnMobile();
  }

  return (
    <Sidebar>
      <SidebarHeader>
        <Link href="/" className="flex items-center gap-2 px-2 py-1">
          <span className="grid size-6 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
            M
          </span>
          <span className="font-semibold">MiniAgent</span>
        </Link>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/"}
              render={<Link href="/" onClick={newChat} />}
            >
              <HugeiconsIcon icon={PencilEdit02Icon} />
              <span>New Chat</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <RepoFolders activeId={activeId} />
      </SidebarContent>

      <SidebarFooter className="gap-3">
        <GettingStarted />
        <AccountFooter />
      </SidebarFooter>
    </Sidebar>
  );
}

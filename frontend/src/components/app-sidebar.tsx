"use client";

import {
  ArrowRight01Icon,
  Delete02Icon,
  Folder01Icon,
  MoreHorizontalIcon,
  PencilEdit02Icon,
  Settings01Icon,
  SidebarLeftIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { memo, useCallback, useMemo, useState } from "react";

import { useAuth } from "@/app/providers";
import { PixelLoader } from "@/components/bui/loading-state";
import {
  SidebarNavGroup,
  SidebarNavIcon,
  SidebarNavLabel,
  SidebarNavSkeleton,
  SidebarNavText,
  sidebarRowClass,
} from "@/components/bui/sidebar-nav";
import { GettingStarted } from "@/components/getting-started";
import { useConversationChanges } from "@/hooks/use-conversation-changes";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar";
import { type ConversationInfo } from "@/lib/api";
import {
  requestComposerFocus,
  setComposerSelection,
} from "@/lib/composer-selection";
import { useConversations, useDeleteConversation } from "@/lib/queries";

const NO_REPO = "No repository";
const SKELETON_WIDTHS = ["70%", "55%", "80%"];

type RepoGroup = { repo: string; chats: ConversationInfo[] };

function conversationLabel(c: ConversationInfo): string {
  const name = c.repo?.split("/").pop();
  if (name && c.title?.startsWith(`${name}: `)) {
    return c.title.slice(name.length + 2);
  }
  return c.title ?? `Chat ${c.id.slice(0, 6)}`;
}

function byCreatedDesc(a: ConversationInfo, b: ConversationInfo) {
  return (b.created_at ?? "").localeCompare(a.created_at ?? "");
}

function groupByRepo(items: ConversationInfo[]): RepoGroup[] {
  const byRepo = new Map<string, ConversationInfo[]>();
  for (const c of items) {
    const key = c.repo ?? NO_REPO;
    const list = byRepo.get(key);
    if (list) list.push(c);
    else byRepo.set(key, [c]);
  }
  return Array.from(byRepo, ([repo, chats]) => ({
    repo,
    chats: chats.sort(byCreatedDesc),
  }));
}

function StatusDot({ status }: { status: ConversationInfo["status"] }) {
  if (status === "running") {
    return (
      <span role="status" aria-label="Running" className="flex shrink-0">
        <PixelLoader className="scale-[0.8]" />
      </span>
    );
  }
  if (status === "waiting_for_confirmation") {
    return (
      <span
        aria-label="Waiting for you"
        className="size-2 shrink-0 rounded-full bg-orange"
      />
    );
  }
  return null;
}

const ChatRow = memo(function ChatRow({
  id,
  label,
  status,
  isActive,
  deleting,
  onDelete,
  onNavigate,
}: {
  id: string;
  label: string;
  status: ConversationInfo["status"];
  isActive: boolean;
  deleting: boolean;
  onDelete: (id: string) => void;
  onNavigate: () => void;
}) {
  return (
    <div
      data-menu-row
      className={sidebarRowClass(isActive, "group/row p-0")}
    >
      <Link
        href={`/chat/${id}`}
        onClick={onNavigate}
        aria-current={isActive ? "page" : undefined}
        className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-[8px] pr-8 pl-[34px]"
      >
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
          {label}
        </span>
        <StatusDot status={status} />
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Chat options"
          className="absolute top-1 right-1 flex size-6 items-center justify-center rounded-[6px] text-ink-3 opacity-0 transition-[opacity,background-color,color] duration-150 group-hover/row:opacity-100 hover:bg-line-strong hover:text-ink focus-visible:opacity-100 data-popup-open:opacity-100"
        >
          <HugeiconsIcon icon={MoreHorizontalIcon} className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start">
          <DropdownMenuItem
            variant="destructive"
            disabled={deleting}
            onClick={() => onDelete(id)}
          >
            <HugeiconsIcon icon={Delete02Icon} />
            Delete chat
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
});

const RepoFolder = memo(function RepoFolder({
  repo,
  chats,
  open,
  onOpenChange,
  activeId,
  deleting,
  onDelete,
  onNavigate,
}: {
  repo: string;
  chats: ConversationInfo[];
  open: boolean;
  onOpenChange: (repo: string, open: boolean) => void;
  activeId: string | null;
  deleting: boolean;
  onDelete: (id: string) => void;
  onNavigate: () => void;
}) {
  const name = repo === NO_REPO ? repo : repo.split("/").pop();

  return (
    <Collapsible
      open={open}
      onOpenChange={(next) => onOpenChange(repo, next)}
      className="flex flex-col gap-px"
    >
      <CollapsibleTrigger
        data-menu-row
        title={repo}
        className={sidebarRowClass(false, "group/folder")}
      >
        <SidebarNavIcon>
          <HugeiconsIcon icon={Folder01Icon} />
        </SidebarNavIcon>
        <SidebarNavText>{name}</SidebarNavText>
        <HugeiconsIcon
          icon={ArrowRight01Icon}
          className="ml-1 size-4 shrink-0 text-ink-3 transition-transform duration-200 ease-(--ease-out-strong) group-data-panel-open/folder:rotate-90"
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="flex animate-[fade-in_180ms_ease-out] flex-col gap-px">
        {chats.map((c) => (
          <ChatRow
            key={c.id}
            id={c.id}
            label={conversationLabel(c)}
            status={c.status}
            isActive={c.id === activeId}
            deleting={deleting}
            onDelete={onDelete}
            onNavigate={onNavigate}
          />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
});

function RepoFolders({
  activeId,
  onNavigate,
}: {
  activeId: string | null;
  onNavigate: () => void;
}) {
  const { data, isPending, isError, refetch } = useConversations();
  const { mutate: deleteConversation, isPending: deleting } =
    useDeleteConversation();
  const groups = useMemo(() => (data ? groupByRepo(data) : []), [data]);
  const active = activeId ? data?.find((c) => c.id === activeId) : undefined;
  const [openRepos, setOpenRepos] = useState<Set<string>>(() => new Set());
  const [lastActive, setLastActive] = useState<string | null>(null);
  if (active && active.id !== lastActive) {
    setLastActive(active.id);
    setOpenRepos((prev) => new Set(prev).add(active.repo ?? NO_REPO));
  }

  const setOpen = useCallback((repo: string, open: boolean) => {
    setOpenRepos((prev) => {
      const next = new Set(prev);
      if (open) next.add(repo);
      else next.delete(repo);
      return next;
    });
  }, []);

  const onDelete = useCallback(
    (id: string) => deleteConversation(id),
    [deleteConversation],
  );

  return (
    <div className="pt-3 pb-2">
      <SidebarNavLabel>Repos</SidebarNavLabel>
      {isPending && <SidebarNavSkeleton widths={SKELETON_WIDTHS} />}
      {isError && (
        <div className="mx-2 flex flex-col items-start gap-1 px-2 py-1.5 text-[12.5px] text-ink-3">
          Couldn&apos;t load chats.
          <button
            type="button"
            onClick={() => refetch()}
            className="font-medium text-ink underline-offset-2 hover:underline"
          >
            Retry
          </button>
        </div>
      )}
      {data?.length === 0 && (
        <p className="mx-2 px-2 py-1.5 text-[12.5px] text-ink-3">
          No chats yet.
        </p>
      )}
      {groups.length > 0 && (
        <SidebarNavGroup>
          {groups.map(({ repo, chats }) => (
            <RepoFolder
              key={repo}
              repo={repo}
              chats={chats}
              open={openRepos.has(repo)}
              onOpenChange={setOpen}
              activeId={activeId}
              deleting={deleting}
              onDelete={onDelete}
              onNavigate={onNavigate}
            />
          ))}
        </SidebarNavGroup>
      )}
    </div>
  );
}

function NewChatRow({
  activeId,
  isActive,
  onNavigate,
}: {
  activeId: string | null;
  isActive: boolean;
  onNavigate: () => void;
}) {
  const { data } = useConversations();
  const activeConv = activeId ? data?.find((c) => c.id === activeId) : undefined;

  function newChat() {
    if (activeConv?.repo) {
      setComposerSelection({ repo: activeConv.repo, branch: activeConv.branch });
    }
    requestComposerFocus();
    onNavigate();
  }

  return (
    <SidebarNavGroup>
      <Link
        data-menu-row
        href="/"
        onClick={newChat}
        aria-current={isActive ? "page" : undefined}
        className={sidebarRowClass(isActive)}
      >
        <SidebarNavIcon>
          <HugeiconsIcon icon={PencilEdit02Icon} />
        </SidebarNavIcon>
        <SidebarNavText>New Chat</SidebarNavText>
      </Link>
    </SidebarNavGroup>
  );
}

function SidebarBrand() {
  const { toggleSidebar } = useSidebar();
  return (
    <div className="flex h-10 items-center justify-between gap-1 pr-2">
      <Link
        href="/"
        className="ml-2 flex h-8 min-w-0 items-center gap-2 rounded-[8px] px-2 transition-[background-color,transform] duration-100 hover:bg-hover-2 active:scale-[0.99]"
      >
        <span className="flex size-5 shrink-0 items-center justify-center rounded-[6px] bg-ink text-[11px] font-semibold text-surface">
          M
        </span>
        <span className="truncate text-[14px] font-semibold text-ink">
          MiniAgent
        </span>
      </Link>
      <button
        type="button"
        aria-label="Toggle sidebar"
        onClick={toggleSidebar}
        className="flex size-8 shrink-0 items-center justify-center rounded-[8px] text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover-2 hover:text-ink active:scale-[0.96]"
      >
        <HugeiconsIcon icon={SidebarLeftIcon} className="size-[18px]" />
      </button>
    </div>
  );
}

export function AccountFooter() {
  const { auth } = useAuth();
  if (!auth) return null;

  const label = auth.github.login ?? auth.user.email ?? "Account";
  const avatar = auth.github.avatar_url ?? auth.user.avatar_url;

  return (
    <div className="mx-2 flex items-center gap-1 border-t border-line pt-2">
      <div className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1">
        <Avatar className="size-6">
          <AvatarImage src={avatar ?? undefined} alt={label} />
          <AvatarFallback className="text-[10px]">
            {label.slice(0, 2).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <span className="truncate text-[13.5px] font-medium text-ink-2">
          {label}
        </span>
      </div>
      <Link
        href="/settings"
        aria-label="Settings"
        className="flex size-8 shrink-0 items-center justify-center rounded-[8px] text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover-2 hover:text-ink active:scale-[0.96]"
      >
        <HugeiconsIcon icon={Settings01Icon} className="size-[18px]" />
      </Link>
    </div>
  );
}

export function useCloseSidebarOnMobile() {
  const { isMobile, setOpenMobile } = useSidebar();
  return useCallback(() => {
    if (isMobile) setOpenMobile(false);
  }, [isMobile, setOpenMobile]);
}

export function AppSidebar() {
  useConversationChanges();
  const pathname = usePathname();
  const closeOnMobile = useCloseSidebarOnMobile();
  const activeId = pathname.startsWith("/chat/")
    ? pathname.slice("/chat/".length)
    : null;

  return (
    <Sidebar>
      <SidebarHeader className="gap-2.5 px-0 pt-2 pb-0">
        <SidebarBrand />
        <NewChatRow
          activeId={activeId}
          isActive={pathname === "/"}
          onNavigate={closeOnMobile}
        />
      </SidebarHeader>

      <SidebarContent className="gap-0">
        <RepoFolders activeId={activeId} onNavigate={closeOnMobile} />
      </SidebarContent>

      <SidebarFooter className="gap-3 px-0 pt-2 pb-2">
        <GettingStarted />
        <AccountFooter />
      </SidebarFooter>
    </Sidebar>
  );
}

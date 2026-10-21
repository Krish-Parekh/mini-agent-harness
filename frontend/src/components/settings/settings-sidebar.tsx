"use client";

import {
  ArrowLeft02Icon,
  Brain01Icon,
  CpuIcon,
  Github01Icon,
  PlugSocketIcon,
  Search01Icon,
  Settings01Icon,
  SparklesIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { AccountFooter, useCloseSidebarOnMobile } from "@/components/app-sidebar";
import {
  SidebarNavGroup,
  SidebarNavIcon,
  SidebarNavText,
  sidebarRowClass,
} from "@/components/bui/sidebar-nav";
import { GettingStarted } from "@/components/getting-started";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar";

export const SETTINGS_SECTIONS = [
  {
    href: "/settings",
    title: "General",
    icon: Settings01Icon,
    keywords: "account email sign out user environment sandbox default",
  },
  {
    href: "/settings/github",
    title: "GitHub",
    icon: Github01Icon,
    keywords: "connection repositories token disconnect reconnect source control",
  },
  {
    href: "/settings/models",
    title: "Models",
    icon: CpuIcon,
    keywords: "default model claude gpt anthropic openai",
  },
  {
    href: "/settings/skills",
    title: "Skills",
    icon: SparklesIcon,
    keywords: "playbooks skills.sh find-skill projects repos slash",
  },
  {
    href: "/settings/memory",
    title: "Memory",
    icon: Brain01Icon,
    keywords: "memories remember notes preferences forget",
  },
  {
    href: "/settings/mcp",
    title: "MCP servers",
    icon: PlugSocketIcon,
    keywords: "model context protocol tools connections",
  },
];

export function SettingsSidebar() {
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const closeOnMobile = useCloseSidebarOnMobile();
  const q = query.trim().toLowerCase();
  const sections = SETTINGS_SECTIONS.filter(
    (s) => !q || `${s.title} ${s.keywords}`.toLowerCase().includes(q),
  );

  return (
    <Sidebar>
      <SidebarHeader className="gap-2.5 px-0 pt-2 pb-0">
        <SidebarNavGroup>
          <Link
            data-menu-row
            href="/"
            onClick={closeOnMobile}
            className={sidebarRowClass()}
          >
            <SidebarNavIcon>
              <HugeiconsIcon icon={ArrowLeft02Icon} />
            </SidebarNavIcon>
            <SidebarNavText>Back</SidebarNavText>
          </Link>
        </SidebarNavGroup>
        <label className="mx-2 flex h-8 items-center rounded-[8px] bg-field text-ink-3 shadow-hairline transition-[color,box-shadow] duration-150 focus-within:text-ink-2 focus-within:shadow-[0_0_0_1px_var(--line-strong)]">
          <span className="ml-2 flex shrink-0 items-center justify-center">
            <HugeiconsIcon icon={Search01Icon} className="size-[15px]" />
          </span>
          <input
            type="search"
            placeholder="Search settings"
            aria-label="Search settings"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="mr-2 ml-1.5 min-w-0 flex-1 bg-transparent text-[13px] font-medium text-ink outline-none placeholder:text-ink-3 [&::-webkit-search-cancel-button]:hidden"
          />
        </label>
      </SidebarHeader>

      <SidebarContent className="gap-0 pt-3 pb-2">
        <SidebarNavGroup>
          {sections.map((s) => {
            const active = pathname === s.href;
            return (
              <Link
                key={s.href}
                data-menu-row
                href={s.href}
                onClick={closeOnMobile}
                aria-current={active ? "page" : undefined}
                className={sidebarRowClass(active)}
              >
                <SidebarNavIcon>
                  <HugeiconsIcon icon={s.icon} />
                </SidebarNavIcon>
                <SidebarNavText>{s.title}</SidebarNavText>
              </Link>
            );
          })}
        </SidebarNavGroup>
        {sections.length === 0 && (
          <p className="mx-2 px-2 py-1.5 text-[12.5px] text-ink-3">
            No settings match.
          </p>
        )}
      </SidebarContent>

      <SidebarFooter className="gap-3 px-0 pt-2 pb-2">
        <GettingStarted />
        <AccountFooter />
      </SidebarFooter>
    </Sidebar>
  );
}

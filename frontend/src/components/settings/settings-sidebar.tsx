"use client";

import {
  ArrowLeft02Icon,
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

import { AccountFooter } from "@/components/app-sidebar";
import { GettingStarted } from "@/components/getting-started";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
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
    keywords: "playbooks import upload markdown slash",
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
  const { isMobile, setOpenMobile } = useSidebar();
  const q = query.trim().toLowerCase();
  const sections = SETTINGS_SECTIONS.filter(
    (s) => !q || `${s.title} ${s.keywords}`.toLowerCase().includes(q),
  );

  function closeOnMobile() {
    if (isMobile) setOpenMobile(false);
  }

  return (
    <Sidebar>
      <SidebarHeader className="gap-3">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton render={<Link href="/" onClick={closeOnMobile} />}>
              <HugeiconsIcon icon={ArrowLeft02Icon} />
              <span>Back</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <InputGroup>
          <InputGroupAddon>
            <HugeiconsIcon icon={Search01Icon} />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            placeholder="Search settings"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </InputGroup>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {sections.map((s) => (
                <SidebarMenuItem key={s.href}>
                  <SidebarMenuButton
                    isActive={pathname === s.href}
                    render={<Link href={s.href} onClick={closeOnMobile} />}
                  >
                    <HugeiconsIcon icon={s.icon} />
                    <span>{s.title}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              {sections.length === 0 && (
                <p className="px-2 py-1.5 text-sm text-muted-foreground">
                  No settings match.
                </p>
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="gap-3">
        <GettingStarted />
        <AccountFooter />
      </SidebarFooter>
    </Sidebar>
  );
}

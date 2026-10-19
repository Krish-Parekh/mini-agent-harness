"use client";

import { McpCard } from "@/components/mcp-card";
import { SkillsPanel } from "@/components/skills-panel";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function CustomizePage() {
  return (
    <div className="flex flex-col">
      <header className="flex h-14 shrink-0 items-center px-4">
        <SidebarTrigger />
      </header>
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 pb-10">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Customize</h1>
          <p className="text-sm text-muted-foreground">
            Skills and MCP servers the agent can use in your chats.
          </p>
        </div>
        <Tabs defaultValue="skills">
          <TabsList>
            <TabsTrigger value="skills">Skills</TabsTrigger>
            <TabsTrigger value="mcp">MCP servers</TabsTrigger>
          </TabsList>
          <TabsContent value="skills" className="pt-4">
            <SkillsPanel />
          </TabsContent>
          <TabsContent value="mcp" className="pt-4">
            <McpCard />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

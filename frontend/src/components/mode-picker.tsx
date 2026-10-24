"use client";

import { Menu } from "@base-ui/react/menu";
import type { KeyboardEvent } from "react";

import { GlideMenu } from "@/components/bui/glide-menu";
import { Glyph, PromptBarButton } from "@/components/bui/prompt-bar";
import type { Modes, PermissionMode } from "@/lib/api";
import { cn } from "@/lib/utils";

const PERMISSIONS: { id: PermissionMode; name: string; description: string }[] = [
  { id: "ask", name: "Ask", description: "Ask before edits and commands that change files." },
  { id: "auto", name: "Auto", description: "Ask only before risky commands and outside paths." },
  { id: "full", name: "Full access", description: "Never ask. Only in a container sandbox." },
];

export const DEFAULT_MODES: Modes = { plan_mode: false, permission_mode: "auto" };

function nextModes(modes: Modes, fullAccess: boolean): Modes {
  if (modes.plan_mode) {
    return { plan_mode: false, permission_mode: fullAccess ? "full" : "ask" };
  }
  if (modes.permission_mode === "ask") return { plan_mode: false, permission_mode: "auto" };
  if (modes.permission_mode === "auto") return { plan_mode: true, permission_mode: "auto" };
  return { plan_mode: false, permission_mode: "ask" };
}

export function cycleOnShiftTab(
  event: KeyboardEvent,
  modes: Modes,
  fullAccess: boolean,
  onChange: (modes: Modes) => void,
): boolean {
  if (event.key !== "Tab" || !event.shiftKey) return false;
  event.preventDefault();
  onChange(nextModes(modes, fullAccess));
  return true;
}

export function ModePicker({
  value,
  fullAccess,
  onChange,
}: {
  value: Modes;
  fullAccess: boolean;
  onChange: (modes: Modes) => void;
}) {
  const options = PERMISSIONS.filter((p) => p.id !== "full" || fullAccess);
  const selected = PERMISSIONS.find((p) => p.id === value.permission_mode);

  return (
    <>
      <PromptBarButton
        aria-pressed={value.plan_mode}
        title="Plan first, without editing. Shift+Tab cycles modes."
        onClick={() => onChange({ ...value, plan_mode: !value.plan_mode })}
        className="aria-pressed:bg-brand-tint aria-pressed:text-brand-ink"
      >
        Plan
      </PromptBarButton>
      <Menu.Root>
        <Menu.Trigger
          render={
            <PromptBarButton
              aria-label="Permission mode"
              className={cn(value.permission_mode === "full" && "text-orange hover:text-orange")}
            />
          }
        >
          <span>{selected?.name}</span>
          <span className="text-ink-3">
            <Glyph size={11} strokeWidth={2.4}>
              <path d="M6 9l6 6 6-6" />
            </Glyph>
          </span>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner
            side="top"
            align="start"
            sideOffset={8}
            className="isolate z-50 outline-none"
          >
            <Menu.Popup className="w-64 origin-(--transform-origin) rounded-card bg-surface p-1 text-ink shadow-raised outline-none data-open:animate-[pop-in_180ms_var(--ease-out-strong)_both]">
              <GlideMenu highlightClassName="inset-x-0 rounded-[6px] bg-hover">
                <Menu.RadioGroup
                  value={value.permission_mode}
                  onValueChange={(v) =>
                    onChange({ ...value, permission_mode: v as PermissionMode })
                  }
                >
                  {options.map((p) => (
                    <Menu.RadioItem
                      key={p.id}
                      value={p.id}
                      closeOnClick
                      data-menu-row
                      className="relative z-10 flex w-full cursor-default items-start gap-2 rounded-[6px] px-2 py-1.5 text-left outline-none select-none"
                    >
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="text-[12.5px] font-medium text-ink">{p.name}</span>
                        <span className="text-[11.5px] text-pretty text-ink-3">
                          {p.description}
                        </span>
                      </span>
                      <Menu.RadioItemIndicator
                        keepMounted
                        className="mt-0.5 shrink-0 text-ink data-unchecked:invisible"
                      >
                        <Glyph size={13} strokeWidth={2.5}>
                          <path d="M20 6L9 17l-5-5" />
                        </Glyph>
                      </Menu.RadioItemIndicator>
                    </Menu.RadioItem>
                  ))}
                </Menu.RadioGroup>
              </GlideMenu>
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>
    </>
  );
}

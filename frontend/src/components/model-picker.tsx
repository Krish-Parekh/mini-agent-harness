"use client";

import { Menu } from "@base-ui/react/menu";

import { GlideMenu } from "@/components/bui/glide-menu";
import { Glyph, PromptBarButton } from "@/components/bui/prompt-bar";

export const MODELS = [
  { id: "anthropic/claude-sonnet-5-5", name: "Claude Sonnet 5.5", provider: "anthropic" },
  { id: "anthropic/claude-opus-5-5", name: "Claude Opus 5.5", provider: "anthropic" },
  { id: "anthropic/claude-haiku-5-5", name: "Claude Haiku 5.5", provider: "anthropic" },
  { id: "openai/responses/gpt-6-luna", name: "GPT-6 Luna", provider: "openai" },
  { id: "openai/responses/gpt-6-sol", name: "GPT-6 Sol", provider: "openai" },
  { id: "openai/responses/gpt-6.1-sol", name: "GPT-6.1 Sol", provider: "openai" },
  { id: "openai/responses/gpt-6-astra", name: "GPT-6 Astra", provider: "openai" },
  { id: "openai/responses/gpt-5.6-luna", name: "GPT-5.6 Luna", provider: "openai" },
  { id: "openai/responses/gpt-5.6-sol", name: "GPT-5.6 Sol", provider: "openai" },
  { id: "gpt-4.1", name: "GPT-4.1", provider: "openai" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 mini", provider: "openai" },
  { id: "gpt-4o-mini", name: "GPT-4o mini", provider: "openai" },
];

export const DEFAULT_MODEL = MODELS[0].id;

export const PROVIDERS = [
  { id: "anthropic", heading: "Anthropic" },
  { id: "openai", heading: "OpenAI" },
];

export function ModelPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (model: string) => void;
}) {
  const selected = MODELS.find((m) => m.id === value);

  return (
    <Menu.Root>
      <Menu.Trigger render={<PromptBarButton />}>
        <span className="max-w-40 truncate">{selected?.name ?? value}</span>
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
          <Menu.Popup className="w-56 origin-(--transform-origin) rounded-card bg-surface p-1 text-ink shadow-raised outline-none data-open:animate-[pop-in_180ms_var(--ease-out-strong)_both]">
            <GlideMenu highlightClassName="inset-x-0 rounded-[6px] bg-hover">
              <Menu.RadioGroup
                value={value}
                onValueChange={(v) => onChange(v as string)}
              >
                {PROVIDERS.map((provider) => (
                  <Menu.Group key={provider.id}>
                    <Menu.GroupLabel className="px-2 pt-1.5 pb-1 text-[11px] font-medium text-ink-3">
                      {provider.heading}
                    </Menu.GroupLabel>
                    {MODELS.filter((m) => m.provider === provider.id).map((m) => (
                      <Menu.RadioItem
                        key={m.id}
                        value={m.id}
                        closeOnClick
                        data-menu-row
                        className="relative z-10 flex h-7.5 w-full cursor-default items-center gap-2 rounded-[6px] px-2 text-left outline-none select-none"
                      >
                        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-ink">
                          {m.name}
                        </span>
                        <Menu.RadioItemIndicator
                          keepMounted
                          className="shrink-0 text-ink data-unchecked:invisible"
                        >
                          <Glyph size={13} strokeWidth={2.5}>
                            <path d="M20 6L9 17l-5-5" />
                          </Glyph>
                        </Menu.RadioItemIndicator>
                      </Menu.RadioItem>
                    ))}
                  </Menu.Group>
                ))}
              </Menu.RadioGroup>
            </GlideMenu>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

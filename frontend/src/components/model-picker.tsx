"use client";

import { CheckIcon } from "lucide-react";
import { useState } from "react";

import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";

export const MODELS = [
  { id: "anthropic/claude-sonnet-5-5", name: "Claude Sonnet 5.5", provider: "anthropic" },
  { id: "anthropic/claude-opus-5-5", name: "Claude Opus 5.5", provider: "anthropic" },
  { id: "anthropic/claude-haiku-5-5", name: "Claude Haiku 5.5", provider: "anthropic" },
  { id: "gpt-4.1", name: "GPT-4.1", provider: "openai" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 mini", provider: "openai" },
  { id: "gpt-4o-mini", name: "GPT-4o mini", provider: "openai" },
];

export const DEFAULT_MODEL = MODELS[0].id;

const PROVIDERS = [
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
  const [open, setOpen] = useState(false);
  const selected = MODELS.find((m) => m.id === value);

  return (
    <ModelSelector open={open} onOpenChange={setOpen}>
      <ModelSelectorTrigger
        render={
          <PromptInputButton>
            <ModelSelectorLogo provider={selected?.provider ?? "anthropic"} />
            <ModelSelectorName>{selected?.name ?? value}</ModelSelectorName>
          </PromptInputButton>
        }
      />
      <ModelSelectorContent className="[&_[data-slot=dialog-close]]:top-2.5 [&_[data-slot=dialog-close]]:right-2.5 [&_[data-slot=command-input-wrapper]]:pr-12">
        <ModelSelectorInput placeholder="Search models…" />
        <ModelSelectorList>
          <ModelSelectorEmpty>No models found.</ModelSelectorEmpty>
          {PROVIDERS.map((provider) => (
            <ModelSelectorGroup key={provider.id} heading={provider.heading}>
              {MODELS.filter((m) => m.provider === provider.id).map((m) => (
                <ModelSelectorItem
                  key={m.id}
                  value={m.id}
                  onSelect={() => {
                    onChange(m.id);
                    setOpen(false);
                  }}
                >
                  <ModelSelectorLogo provider={m.provider} />
                  <ModelSelectorName>{m.name}</ModelSelectorName>
                  {value === m.id ? (
                    <CheckIcon className="ml-auto size-4" />
                  ) : (
                    <div className="ml-auto size-4" />
                  )}
                </ModelSelectorItem>
              ))}
            </ModelSelectorGroup>
          ))}
        </ModelSelectorList>
      </ModelSelectorContent>
    </ModelSelector>
  );
}

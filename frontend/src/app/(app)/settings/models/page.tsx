"use client";

import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from "@/components/settings/settings-ui";
import { DEFAULT_MODEL, MODELS, PROVIDERS } from "@/components/model-picker";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  setComposerSelection,
  useComposerSelection,
} from "@/lib/composer-selection";

const nameOf = (id: string) => MODELS.find((m) => m.id === id)?.name ?? id;

export default function ModelsSettingsPage() {
  const selection = useComposerSelection();
  const value = selection.model ?? DEFAULT_MODEL;

  return (
    <SettingsPage title="Models">
      <SettingsGroup>
        <SettingsRow
          title="Default model"
          description="The model new chats start with. You can switch models any time from the composer."
        >
          <Select
            value={value}
            onValueChange={(v) => setComposerSelection({ model: v as string })}
          >
            <SelectTrigger size="sm" className="min-w-44">
              <SelectValue>{(v: string) => nameOf(v)}</SelectValue>
            </SelectTrigger>
            <SelectContent align="end">
              <SelectGroup>
                {MODELS.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Available models">
        {MODELS.map((m) => (
          <SettingsRow
            key={m.id}
            title={m.name}
            description={<code className="text-xs">{m.id}</code>}
          >
            <span className="text-xs text-muted-foreground">
              {PROVIDERS.find((p) => p.id === m.provider)?.heading}
            </span>
          </SettingsRow>
        ))}
      </SettingsGroup>
    </SettingsPage>
  );
}

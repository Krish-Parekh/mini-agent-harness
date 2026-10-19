"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
  SettingsEmpty,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from "@/components/settings/settings-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { queryKeys, useSkills } from "@/lib/queries";

export default function SkillsSettingsPage() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const { data: skills, isPending } = useSkills();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.skills });

  const importSkill = useMutation({
    mutationFn: (value: string) => api.importSkill(value),
    onSuccess: (skill) => {
      setUrl("");
      invalidate();
      toast.success(`Imported “${skill.name}”`);
    },
    onError: (e) => toast.error(messageFor(e)),
  });

  const uploadSkill = useMutation({
    mutationFn: async (file: File) =>
      api.createSkill({
        name: file.name.replace(/\.md$/i, ""),
        description: "",
        body: await file.text(),
      }),
    onSuccess: (skill) => {
      invalidate();
      toast.success(`Added “${skill.name}”`);
    },
    onError: (e) => toast.error(messageFor(e)),
  });

  const removeSkill = useMutation({
    mutationFn: (id: string) => api.deleteSkill(id),
    onSuccess: invalidate,
    onError: (e) => toast.error(messageFor(e)),
  });

  return (
    <SettingsPage title="Skills">
      <SettingsGroup
        title="Add a skill"
        description="Playbooks the agent can follow. Type / in a composer to enable one for a chat."
      >
        <SettingsRow
          title="Import from URL"
          description="An https link to a Markdown file, up to 256 KB."
        >
          <form
            className="flex w-full gap-2 sm:w-80"
            onSubmit={(e) => {
              e.preventDefault();
              if (url.trim()) importSkill.mutate(url.trim());
            }}
          >
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/skill.md"
              className="h-8"
            />
            <Button
              type="submit"
              size="sm"
              variant="outline"
              disabled={!url.trim() || importSkill.isPending}
            >
              {importSkill.isPending ? "Importing…" : "Import"}
            </Button>
          </form>
        </SettingsRow>
        <SettingsRow
          title="Upload a file"
          description="A .md file from your computer."
        >
          <input
            ref={fileInput}
            type="file"
            accept=".md,text/markdown,text/plain"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadSkill.mutate(file);
              e.target.value = "";
            }}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={uploadSkill.isPending}
          >
            {uploadSkill.isPending ? "Uploading…" : "Choose file"}
          </Button>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Your skills">
        {isPending ? (
          <div className="flex flex-col gap-3 py-4">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-5 w-2/3" />
          </div>
        ) : !skills?.length ? (
          <SettingsEmpty>No skills yet. Import or upload one above.</SettingsEmpty>
        ) : (
          skills.map((skill) => (
            <SettingsRow
              key={skill.id}
              title={skill.name}
              description={
                <span className="flex flex-col gap-0.5">
                  <span className="line-clamp-2">
                    {skill.description || "No description"}
                  </span>
                  <span className="text-xs text-muted-foreground/80">
                    {skill.created_at &&
                      `Added ${new Date(skill.created_at).toLocaleDateString()}`}
                    {skill.source_url && (
                      <>
                        {skill.created_at && " · "}
                        <a
                          href={skill.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline"
                        >
                          source
                        </a>
                      </>
                    )}
                  </span>
                </span>
              }
            >
              <Button
                size="sm"
                variant="outline"
                disabled={removeSkill.isPending}
                onClick={() => removeSkill.mutate(skill.id)}
              >
                Delete
              </Button>
            </SettingsRow>
          ))
        )}
      </SettingsGroup>
    </SettingsPage>
  );
}

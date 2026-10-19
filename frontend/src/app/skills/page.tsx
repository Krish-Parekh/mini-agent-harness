"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { RequireAuth } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, type Skill } from "@/lib/api";
import { messageFor } from "@/lib/errors";

function SkillRow({ skill, onDelete }: { skill: Skill; onDelete: () => void }) {
  return (
    <li className="flex items-start justify-between gap-4 border-b py-3 last:border-b-0">
      <div className="min-w-0">
        <p className="truncate font-medium">{skill.name}</p>
        <p className="truncate text-sm text-muted-foreground">
          {skill.description || "No description"}
        </p>
        {skill.source_url && (
          <a
            href={skill.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-muted-foreground underline"
          >
            {skill.source_url}
          </a>
        )}
      </div>
      <Button variant="outline" size="sm" onClick={onDelete}>
        Delete
      </Button>
    </li>
  );
}

function SkillsBody() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const { data: skills, isPending } = useQuery({
    queryKey: ["skills"],
    queryFn: api.skills,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["skills"] });

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
    mutationFn: async (file: File) => {
      const body = await file.text();
      return api.createSkill({
        name: file.name.replace(/\.md$/i, ""),
        description: `Uploaded from ${file.name}`,
        body,
      });
    },
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
    <div className="mx-auto w-full max-w-2xl px-6 py-10">
      <div className="mb-8">
        <Link href="/" className="text-sm text-muted-foreground underline">
          Back
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">Skills</h1>
        <p className="text-sm text-muted-foreground">
          Playbooks the agent can follow. Enable them per chat from the Context
          panel.
        </p>
      </div>

      <div className="mb-8 space-y-3 rounded-lg border p-4">
        <h2 className="text-sm font-medium">Add a skill</h2>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (url.trim()) importSkill.mutate(url.trim());
          }}
        >
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/skill.md"
          />
          <Button type="submit" disabled={!url.trim() || importSkill.isPending}>
            {importSkill.isPending ? "Importing…" : "Import"}
          </Button>
        </form>
        <div className="flex items-center gap-2">
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
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={uploadSkill.isPending}
          >
            {uploadSkill.isPending ? "Uploading…" : "Upload a .md file"}
          </Button>
          <span className="text-xs text-muted-foreground">
            https only, 256 KB max
          </span>
        </div>
      </div>

      {isPending ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="size-4" />
          Loading…
        </div>
      ) : !skills?.length ? (
        <p className="text-sm text-muted-foreground">
          No skills yet — import one above.
        </p>
      ) : (
        <ul>
          {skills.map((skill) => (
            <SkillRow
              key={skill.id}
              skill={skill}
              onDelete={() => removeSkill.mutate(skill.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SkillsPage() {
  return (
    <RequireAuth>
      <SkillsBody />
    </RequireAuth>
  );
}

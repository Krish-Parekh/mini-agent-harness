"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, type Repo } from "@/lib/api";
import { useImportRepo } from "@/lib/queries";

export function ImportRepoDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported?: (repo: Repo) => void;
}) {
  const [value, setValue] = useState("");
  const importRepo = useImportRepo();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const repo = value.trim();
    if (!repo || importRepo.isPending) return;
    importRepo.mutate(repo, {
      onSuccess: (imported) => {
        setValue("");
        onOpenChange(false);
        onImported?.(imported);
      },
    });
  }

  const error = importRepo.isError
    ? importRepo.error instanceof ApiError && importRepo.error.status === 404
      ? "Repository not found or not accessible."
      : "Couldn’t import that repository. Check the URL and try again."
    : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) importRepo.reset();
      }}
    >
      <DialogContent>
        <form onSubmit={submit} className="grid gap-6">
          <DialogHeader>
            <DialogTitle>Import a repository</DialogTitle>
            <DialogDescription>
              Paste a GitHub URL or owner/name. It’ll be forked into your account
              so the agent can work on it.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Input
              autoFocus
              placeholder="owner/name or https://github.com/owner/name"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              Cancel
            </DialogClose>
            <Button type="submit" disabled={!value.trim() || importRepo.isPending}>
              {importRepo.isPending ? "Importing…" : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

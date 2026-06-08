"use client";

import { useState } from "react";

import { GitForkIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { useImportRepo } from "@/lib/queries";

export function ImportRepoDialog() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const importRepo = useImportRepo();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const repo = value.trim();
    if (!repo || importRepo.isPending) return;
    importRepo.mutate(repo, {
      onSuccess: () => {
        setValue("");
        setOpen(false);
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
        setOpen(next);
        if (!next) importRepo.reset();
      }}
    >
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <HugeiconsIcon icon={GitForkIcon} data-icon="inline-start" />
        Import
      </DialogTrigger>
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

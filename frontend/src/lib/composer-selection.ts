import { useSyncExternalStore } from "react";

export type ComposerSelection = {
  repo: string | null;
  branch: string | null;
  environment: string | null;
  model: string | null;
};

const KEY = "miniagent:composer-selection";
const EMPTY: ComposerSelection = {
  repo: null,
  branch: null,
  environment: null,
  model: null,
};

const listeners = new Set<() => void>();
let cached: ComposerSelection | null = null;
let focusTick = 0;

function read(): ComposerSelection {
  if (cached) return cached;
  try {
    const raw = window.localStorage.getItem(KEY);
    cached = raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    cached = EMPTY;
  }
  return cached!;
}

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setComposerSelection(patch: Partial<ComposerSelection>) {
  cached = { ...read(), ...patch };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(cached));
  } catch {}
  emit();
}

export function useComposerSelection(): ComposerSelection {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

export function requestComposerFocus() {
  focusTick += 1;
  emit();
}

export function useComposerFocusTick(): number {
  return useSyncExternalStore(
    subscribe,
    () => focusTick,
    () => 0,
  );
}

"use client";

import { type KeyboardEvent, useCallback, useState } from "react";

const DRAFT_PREFIX = "miniagent:draft:";
const HISTORY_KEY = "miniagent:prompt-history";
const MAX_HISTORY = 50;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {}
}

function readHistory(): string[] {
  try {
    return JSON.parse(read(HISTORY_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

type ComposerState = { key: string; text: string; browsing: number | null };

function initial(key: string): ComposerState {
  return { key, text: read(DRAFT_PREFIX + key) ?? "", browsing: null };
}

export function useComposerText(draftKey: string) {
  const [state, setState] = useState(() => initial(draftKey));

  if (state.key !== draftKey) setState(initial(draftKey));

  const show = useCallback(
    (text: string, browsing: number | null) => {
      write(DRAFT_PREFIX + draftKey, text);
      setState({ key: draftKey, text, browsing });
    },
    [draftKey],
  );

  const setText = useCallback((text: string) => show(text, null), [show]);

  function record(sent: string) {
    const history = readHistory().filter((entry) => entry !== sent);
    write(HISTORY_KEY, JSON.stringify([...history, sent].slice(-MAX_HISTORY)));
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    const history = readHistory();
    const index = state.browsing;
    const unedited = index === null ? state.text === "" : state.text === history[index];
    if (!unedited) return;
    if (e.key === "ArrowUp") {
      const next = (index ?? history.length) - 1;
      if (next < 0) return;
      e.preventDefault();
      show(history[next], next);
    } else if (index !== null) {
      e.preventDefault();
      const next = index + 1;
      show(history[next] ?? "", next < history.length ? next : null);
    }
  }

  return { text: state.text, setText, record, onKeyDown };
}

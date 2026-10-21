"use client";

import { useEffect, useRef, useState } from "react";

export function useDelayedFlag(active: boolean, delayMs = 400, minVisibleMs = 400) {
  const [visible, setVisible] = useState(false);
  const shownAt = useRef(0);

  useEffect(() => {
    if (active === visible) return;
    const wait = active
      ? delayMs
      : Math.max(0, minVisibleMs - (Date.now() - shownAt.current));
    const timer = setTimeout(() => {
      if (active) shownAt.current = Date.now();
      setVisible(active);
    }, wait);
    return () => clearTimeout(timer);
  }, [active, visible, delayMs, minVisibleMs]);

  return visible;
}

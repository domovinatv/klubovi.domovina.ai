import { useEffect, useState } from "react";

const KEY = "klubovi.layout.wide";

function readInitial(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function applyAttr(wide: boolean) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(
    "data-layout",
    wide ? "wide" : "narrow",
  );
}

// Apply on module import so initial render matches stored preference and
// avoids a flash from narrow → wide.
applyAttr(readInitial());

export function useWideLayout(): [boolean, () => void] {
  const [wide, setWide] = useState(readInitial);

  useEffect(() => {
    applyAttr(wide);
    try {
      window.localStorage.setItem(KEY, wide ? "1" : "0");
    } catch {
      // ignore quota / private mode
    }
  }, [wide]);

  // Sync across tabs.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setWide(e.newValue === "1");
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return [wide, () => setWide((w) => !w)];
}

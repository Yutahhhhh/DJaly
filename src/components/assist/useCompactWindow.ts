import { useCallback, useEffect, useState } from "react";
import { getErrorDetail } from "@/services/api-client";
import { assistService, isDesktopShell } from "@/services/assist";

/** Wide enough for a title plus its reasons, short enough to sit beside rekordbox. */
export const COMPACT_WIDTH = 440;
export const COMPACT_HEIGHT = 650;

// Serialize enter/exit even across React development remounts.
let windowOperation: Promise<unknown> = Promise.resolve();
function enqueue<T>(operation: () => Promise<T>): Promise<T> {
  const next = windowOperation.then(operation, operation);
  windowOperation = next.catch(() => undefined);
  return next;
}

export interface CompactWindow {
  alwaysOnTop: boolean;
  setAlwaysOnTop: (enabled: boolean) => void;
  /** Non-null when the window could not be resized or pinned. */
  message: string | null;
  supported: boolean;
}

/**
 * Shrinks the main window while assist mode is active and puts back exactly the
 * bounds it had on the way out. The previous geometry is remembered natively, so
 * a webview reload in between cannot lose it.
 */
export function useCompactWindow(active: boolean): CompactWindow {
  const [alwaysOnTop, setPinned] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const supported = isDesktopShell();

  useEffect(() => {
    if (!active || !supported) return;
    let live = true;
    void enqueue(() => assistService.enterCompactWindow(COMPACT_WIDTH, COMPACT_HEIGHT))
      .then((result) => {
        if (live && result.message) setMessage(result.message);
      })
      .catch((failure) => {
        if (live) setMessage(getErrorDetail(failure));
      });
    return () => {
      live = false;
      // Leaving assist mode must not leave the window pinned over rekordbox.
      void enqueue(() => assistService.setAlwaysOnTop(false)).catch(() => undefined);
      void enqueue(() => assistService.exitCompactWindow()).catch(() => undefined);
    };
  }, [active, supported]);

  const setAlwaysOnTop = useCallback(
    (enabled: boolean) => {
      if (!supported) return;
      setPinned(enabled);
      void enqueue(() => assistService.setAlwaysOnTop(enabled)).catch((failure) => {
        setPinned(!enabled);
        setMessage(getErrorDetail(failure));
      });
    },
    [supported],
  );

  return { alwaysOnTop, setAlwaysOnTop, message, supported };
}

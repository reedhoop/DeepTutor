"use client";

/**
 * KgTabContext — bridges in-message / activity "open in viewer" CTAs to the
 * SessionViewerPanel's imperative ``openKgTab``.
 *
 * Pattern mirrors GeogebraTabContext (but much smaller — no persistent
 * thread state). A CTA (the ```kgraph fence card, or the Activity-home
 * shortcut) calls ``useKgTabOpener()`` and dispatches; the chat page wires
 * the controller's open-handler to the viewer panel ref via ``setOpenHandler``.
 */

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
} from "react";

export interface KgTabPayload {
  /** Stable id for tab dedupe — same concept should map to the same tab. */
  id: string;
  /** Optional concept name to focus the browser on (resolved on open). */
  concept?: string;
  /** Display label on the tab strip. */
  title?: string;
}

export interface KgTabController {
  /** Open or focus a KG browser tab in the side viewer. */
  openTab(payload: KgTabPayload): void;
  /** The chat page registers the viewer-panel's ``openKgTab`` here. */
  setOpenHandler(handler: ((payload: KgTabPayload) => void) | null): void;
}

const KgTabCtx = createContext<KgTabController | null>(null);

export function KgTabProvider({ children }: { children: ReactNode }) {
  // The handler is mutable — the chat page can swap it via setOpenHandler
  // without forcing every consumer to re-render. Stored in a ref so the
  // controller object itself stays stable across renders.
  const handlerRef = useRef<((payload: KgTabPayload) => void) | null>(null);

  const openTab = useCallback((payload: KgTabPayload) => {
    const handler = handlerRef.current;
    if (handler) {
      handler(payload);
    } else {
      // No viewer registered yet (or page hasn't mounted the bridge). The
      // CTA click is a no-op rather than throwing; the user can retry once
      // the viewer is available.
      console.warn("[KgTabContext] No open handler registered; ignoring openTab()");
    }
  }, []);

  const setOpenHandler = useCallback(
    (handler: ((payload: KgTabPayload) => void) | null) => {
      handlerRef.current = handler;
    },
    [],
  );

  const controller = useMemo<KgTabController>(
    () => ({ openTab, setOpenHandler }),
    [openTab, setOpenHandler],
  );

  return <KgTabCtx.Provider value={controller}>{children}</KgTabCtx.Provider>;
}

/**
 * Hook for descendants that need to open a KG tab. Returns ``null`` when no
 * provider is mounted — callers should treat that as "feature unavailable"
 * and degrade gracefully (e.g. don't render the CTA at all).
 */
export function useKgTabOpener(): KgTabController | null {
  return useContext(KgTabCtx);
}

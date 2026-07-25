"use client";

import { createContext, useContext } from "react";

/* ── Context so EngineCard reads busy without re-rendering when it flips ── */
export const BusyContext = createContext(false);

export function useBusy() {
  return useContext(BusyContext);
}

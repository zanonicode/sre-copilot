"use client";

import { useEffect } from "react";
import { initBrowserOtel, measureWebVitals } from "../../observability";

export function OtelInitializer() {
  useEffect(() => {
    initBrowserOtel();
    measureWebVitals();
  }, []);

  return null;
}

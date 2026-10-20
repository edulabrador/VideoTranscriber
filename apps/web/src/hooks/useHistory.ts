import { useCallback, useEffect, useState } from "react";

import { getJson } from "../api/client";
import type { HistoryItem } from "../api/types";

export function useHistory(query = "") {
  const [entries, setEntries] = useState<HistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => {
    setRevision((value) => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      getJson<HistoryItem[]>(`/api/history?q=${encodeURIComponent(query)}`, controller.signal)
        .then((items) => { if (!controller.signal.aborted) { setEntries(items); setError(null); } })
        .catch((err) => {
          if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "No se pudo cargar el historial");
        });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, revision]);

  return { entries, refresh, error };
}

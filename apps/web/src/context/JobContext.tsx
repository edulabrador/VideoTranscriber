import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from "react";

import { JOB_STORAGE_KEY, reducer, restoreJob, type JobAction, type JobState } from "./jobState";

const JobContext = createContext<{ state: JobState; dispatch: Dispatch<JobAction> } | null>(null);

export function JobProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, () => restoreJob(window.localStorage));
  useEffect(() => {
    try {
      if (state.jobId && state.status !== "failed" && state.status !== "cancelled") {
        localStorage.setItem(JOB_STORAGE_KEY, state.jobId);
      } else {
        localStorage.removeItem(JOB_STORAGE_KEY);
      }
    } catch { /* Transcription still works without browser storage. */ }
  }, [state.jobId, state.status]);
  return <JobContext.Provider value={{ state, dispatch }}>{children}</JobContext.Provider>;
}

// The provider and its hook deliberately share this small context module.
// eslint-disable-next-line react-refresh/only-export-components
export function useJobContext() {
  const ctx = useContext(JobContext);
  if (!ctx) throw new Error("useJobContext must be used within a JobProvider");
  return ctx;
}

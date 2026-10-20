import type { JobError, JobStatus, TranscriptResult } from "../api/types";

export const JOB_STORAGE_KEY = "videotranscriber-job-id";

export interface JobState {
  jobId: string | null;
  status: JobStatus | null;
  stageMessage: string;
  progressPercent: number;
  result: TranscriptResult | null;
  error: JobError | null;
  connectionMessage: string | null;
}

export type JobAction =
  | { type: "START_JOB"; jobId: string }
  | { type: "UPDATE_STATUS"; status: JobStatus; stageMessage: string; progressPercent: number; error: JobError | null }
  | { type: "SET_RESULT"; result: TranscriptResult }
  | { type: "CONNECTION_ERROR"; message: string }
  | { type: "RESET" };

const initialState: JobState = {
  jobId: null, status: null, stageMessage: "", progressPercent: 0,
  result: null, error: null, connectionMessage: null,
};

export function restoreJob(storage: Pick<Storage, "getItem">): JobState {
  try {
    const jobId = storage.getItem(JOB_STORAGE_KEY);
    if (jobId && /^job_[A-Za-z0-9_-]{1,64}$/.test(jobId)) {
      return { ...initialState, jobId, status: "queued", stageMessage: "Recuperando la transcripción..." };
    }
  } catch { /* Storage may be disabled by the browser. */ }
  return initialState;
}

export function reducer(state: JobState, action: JobAction): JobState {
  switch (action.type) {
    case "START_JOB":
      return { ...initialState, jobId: action.jobId, status: "queued" };
    case "UPDATE_STATUS":
      return {
        ...state, status: action.status, stageMessage: action.stageMessage,
        progressPercent: action.progressPercent, error: action.error, connectionMessage: null,
      };
    case "SET_RESULT":
      return { ...state, status: "completed", result: action.result, connectionMessage: null };
    case "CONNECTION_ERROR":
      return { ...state, connectionMessage: action.message };
    case "RESET":
      return initialState;
  }
}

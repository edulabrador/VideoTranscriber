import type { JobStatusResponse, TranscriptResult } from "../api/types";

export async function loadJobUpdate(
  jobId: string,
  request: <T>(path: string) => Promise<T>,
) {
  const job = await request<JobStatusResponse>(`/api/jobs/${jobId}`);
  const result = job.status === "completed"
    ? await request<TranscriptResult>(`/api/jobs/${jobId}/result`)
    : null;
  return { job, result };
}

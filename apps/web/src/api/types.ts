export type JobStatus =
  | "queued"
  | "loading_model"
  | "downloading"
  | "extracting_audio"
  | "transcribing"
  | "exporting"
  | "completed"
  | "failed"
  | "cancelling"
  | "cancelled";

export function isTerminalStatus(status: JobStatus | null): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

export type TranscriptionProfile = "fast" | "balanced" | "precise";
export type AudioQuality = "compact" | "balanced" | "best";

export interface JobResponse {
  id: string;
  status: JobStatus;
  cached: boolean;
}

export interface JobError {
  code: string;
  message: string;
}

export interface JobStatusResponse {
  id: string;
  status: JobStatus;
  stage_message: string;
  progress_percent: number;
  error: JobError | null;
}

export interface TranscriptWord {
  start: number;
  end: number;
  word: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  words: TranscriptWord[];
}

export interface TranscriptResult {
  timings?: Record<string, number>;
  segments: TranscriptSegment[];
  language: string;
  language_probability: number;
  duration: number;
  word_count: number;
  text: string;
  model_size: string;
  device: string;
  compute_type: string;
  batch_size: number;
  profile: TranscriptionProfile;
  audio_language?: string | null;
  audio_format_id?: string | null;
  audio_selection?: "original" | "default" | null;
}

export interface HistoryItem {
  id: string;
  source_type: "url" | "file";
  source: string;
  title: string;
  created_at: string;
  duration: number;
  word_count: number;
  language: string;
  text?: string;
}

export interface HealthResponse {
  status: string;
  ffmpeg: boolean;
  device: string;
  compute_type: string;
  gpu_memory_mb: number | null;
  batch_size: number;
}

export type ExportFormat = "txt" | "srt" | "json";

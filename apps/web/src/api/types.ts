export type JobStatus =
  | "queued"
  | "loading_model"
  | "downloading"
  | "extracting_audio"
  | "transcribing"
  | "diarizing"
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
export type TranscriptionTask = "transcribe" | "translate";

export interface TranscriptionOptions {
  language: string | null;
  task: TranscriptionTask;
  initial_prompt: string | null;
  word_timestamps: boolean;
  diarize: boolean;
  num_speakers: number | null;
}

export const DEFAULT_OPTIONS: TranscriptionOptions = {
  language: null,
  task: "transcribe",
  initial_prompt: null,
  word_timestamps: false,
  diarize: false,
  num_speakers: null,
};

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
  source?: string;
  created_at?: string;
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
  speaker?: string | null;
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
  requested_language?: string | null;
  task?: TranscriptionTask;
  initial_prompt?: string | null;
  word_timestamps?: boolean;
  diarize?: boolean;
  num_speakers?: number | null;
  source?: string;
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
  status?: "completed" | "failed";
  error?: string | null;
}

export interface HealthResponse {
  status: string;
  ffmpeg: boolean;
  device: string;
  compute_type: string;
  gpu_memory_mb: number | null;
  batch_size: number;
}

export type ExportFormat = "txt" | "md" | "srt" | "vtt" | "json";

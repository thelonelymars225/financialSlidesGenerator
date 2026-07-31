import type { DeckPurpose } from "../extraction/types";

export type GenerationStatus =
  | "queued"
  | "analyzing"
  | "rendering"
  | "succeeded"
  | "failed";

export type GenerationFailure = {
  code: string;
  message: string;
  retryable: boolean;
};

export type GenerationJob = {
  id: string;
  extraction_job_id: string;
  deck_type: DeckPurpose;
  slide_count: number;
  status: GenerationStatus;
  progress: number;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  failure: GenerationFailure | null;
};

export type SlideSource = {
  documentId?: string;
  pageNumber?: number;
  blockId?: string;
  quote?: string;
};

export type SlideComponent = {
  id: string;
  type: string;
  label?: string;
  statement?: string;
  text?: string;
  value?: {
    displayedValue?: string;
    value?: number;
    normalizedValue?: number;
    unit?: string;
    period?: string;
  };
  sources?: SlideSource[];
};

export type SlideSpec = {
  title: string;
  subtitle?: string;
  slides: Array<{
    id: string;
    order: number;
    title: string;
    components: SlideComponent[];
  }>;
};

export type GenerationResult = {
  job: GenerationJob;
  slide_spec: SlideSpec;
  download_url: string;
};

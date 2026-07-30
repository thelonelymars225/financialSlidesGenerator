export type InputMode = "file" | "text";
export type DeckPurpose = "management-review" | "board-update" | "investor-summary";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type JobFailure = {
  code: string;
  message: string;
};

export type JobTelemetry = {
  route: string;
  duration_ms: number;
  retries: number;
  external_cost_usd: number;
};

export type ExtractionWarning = {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
};

export type ExtractionJob = {
  id: string;
  input_mode: InputMode;
  file_name: string | null;
  deck_purpose: string;
  slide_count: number;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  attempt_count: number;
  max_attempts: number;
  failure: JobFailure | null;
  telemetry: JobTelemetry | null;
};

export type CreateJobRequest = {
  input_mode: InputMode;
  source_text?: string;
  file_name?: string;
  file_content_base64?: string;
  declared_media_type?: string;
  deck_purpose: DeckPurpose;
  slide_count: number;
  request_key: string;
};

export type SourceReference = {
  sourceId?: string;
  pageNumber?: number;
  sectionPath?: string[];
};

export type ExtractedBlock = {
  id?: string;
  type?: string;
  order?: number;
  text?: string;
  caption?: string;
  cells?: Array<{
    row?: number;
    column?: number;
    text?: string;
    source?: SourceReference;
  }>;
  source?: SourceReference;
  confidence?: number;
  warnings?: ExtractionWarning[];
};

export type ExtractedDocument = {
  schemaVersion?: string;
  documentId?: string;
  source?: {
    sourceId?: string;
    inputType?: string;
    mediaType?: string;
    fileName?: string;
    contentHash?: string;
  };
  pages?: Array<{
    pageNumber?: number;
    blocks?: ExtractedBlock[];
  }>;
  warnings?: ExtractionWarning[];
};

export type JobResult = {
  job: ExtractionJob;
  document: ExtractedDocument;
};

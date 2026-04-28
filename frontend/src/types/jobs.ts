/** Enumerate the supported job type values accepted by the API. */
export type JobType = "echo" | "reverse" | "uppercase";

/** Enumerate the persisted job lifecycle states returned by the API. */
export type JobStatus = "queued" | "processing" | "completed" | "failed";

/** Describe the payload used to create a new job through the API. */
export interface JobCreateRequestPayload {
  input_value: string;
  job_type: JobType;
  maximum_attempt_count?: number;
}

/** Describe a persisted job record returned by the API. */
export interface JobStatusResponse {
  id: string;
  input_value: string;
  job_type: JobType;
  status: JobStatus;
  attempt_count: number;
  maximum_attempt_count: number;
  result: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/** Describe the optional query parameters used when listing jobs. */
export interface ListJobRecordsOptions {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}
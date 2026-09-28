/** Enumerate the supported job type values accepted by the API. */
export type JobType = "echo" | "reverse" | "uppercase";

/** Enumerate the persisted job lifecycle states returned by the API. */
export type JobStatus = "queued" | "processing" | "completed" | "failed" | "dead_lettered";

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
  dead_lettered_at: string | null;
  replayed_from_job_id: string | null;
  created_at: string;
  updated_at: string;
}

/** Enumerate the version-one job lifecycle event values. */
export type JobLifecycleEventType =
  | "submitted"
  | "processing"
  | "retry_scheduled"
  | "completed"
  | "dead_lettered"
  | "replayed";

/** Describe one typed lifecycle event returned from the Kafka history projection. */
export interface JobLifecycleEventResponse {
  schema_version: 1;
  event_id: string;
  event_type: JobLifecycleEventType;
  occurred_at: string;
  job_id: string;
  sequence_number: number;
  job_type: JobType;
  status: JobStatus;
  attempt_count: number;
  maximum_attempt_count: number;
  error_message: string | null;
  replayed_from_job_id: string | null;
}

/** Describe the rolling operations metrics returned by the API. */
export interface OperationsMetricsResponse {
  sampled_at: string;
  window_seconds: number;
  throughput_jobs_per_minute: number;
  retry_rate_percent: number;
  failure_rate_percent: number;
  outbox_backlog: number;
  kafka_consumer_lag: number;
}

/** Describe the optional query parameters used when listing jobs. */
export interface ListJobRecordsOptions {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}
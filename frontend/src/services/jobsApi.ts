import type {
  JobCreateRequestPayload,
  JobStatusResponse,
  ListJobRecordsOptions,
} from "../types/jobs";


const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";


/** Build an absolute API path from the configured frontend base URL. */
function buildApiUrl(pathname: string): string {
  return `${apiBaseUrl}${pathname}`;
}


/** Throw an informative error when an API call fails. */
async function readErrorMessage(response: Response): Promise<string> {
  const responseText = await response.text();

  if (!responseText) {
    return `Request failed with status ${response.status}`;
  }

  return responseText;
}


/** Fetch and decode JSON from the backend API. */
async function fetchJson<TResponse>(request: RequestInfo | URL, init?: RequestInit): Promise<TResponse> {
  const response = await fetch(request, init);

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as TResponse;
}


/** Submit a new job to the backend API. */
export async function createJobRecord(
  jobCreateRequestPayload: JobCreateRequestPayload,
): Promise<JobStatusResponse> {
  return fetchJson<JobStatusResponse>(buildApiUrl("/jobs"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(jobCreateRequestPayload),
  });
}


/** Retrieve one persisted job record by its identifier. */
export async function fetchJobRecord(
  jobIdentifier: string,
  abortSignal?: AbortSignal,
): Promise<JobStatusResponse> {
  return fetchJson<JobStatusResponse>(buildApiUrl(`/jobs/${jobIdentifier}`), {
    signal: abortSignal,
  });
}


/** Replay a dead-lettered job and return the newly queued job record. */
export async function replayJobRecord(jobIdentifier: string): Promise<JobStatusResponse> {
  return fetchJson<JobStatusResponse>(buildApiUrl(`/jobs/${jobIdentifier}/replay`), {
    method: "POST",
  });
}


/** Retrieve a filtered list of persisted job records. */
export async function listJobRecords(
  listJobRecordsOptions: ListJobRecordsOptions = {},
): Promise<JobStatusResponse[]> {
  const queryParameters = new URLSearchParams();

  if (listJobRecordsOptions.status !== undefined) {
    queryParameters.set("status", listJobRecordsOptions.status);
  }

  queryParameters.set("limit", String(listJobRecordsOptions.limit ?? 12));
  queryParameters.set("offset", String(listJobRecordsOptions.offset ?? 0));

  return fetchJson<JobStatusResponse[]>(buildApiUrl(`/jobs?${queryParameters.toString()}`));
}
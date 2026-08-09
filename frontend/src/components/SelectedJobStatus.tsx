import type { ReactElement } from "react";

import type { JobStatusResponse } from "../types/jobs";


export interface SelectedJobStatusProperties {
  selectedJobIdentifier: string | null;
  selectedJobRecord: JobStatusResponse | null;
  isLoadingSelectedJobRecord: boolean;
  selectedJobRecordErrorMessage: string | null;
  isReplayingSelectedJob: boolean;
  replayErrorMessage: string | null;
  replaySuccessMessage: string | null;
  onReloadSelectedJobRecord: () => Promise<void>;
  onReplaySelectedJob: () => Promise<void>;
}


/** Format an ISO timestamp for the dashboard UI. */
function formatTimestamp(timestampValue: string): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestampValue));
}


/** Render the live status view for the currently selected job. */
export function SelectedJobStatus({
  selectedJobIdentifier,
  selectedJobRecord,
  isLoadingSelectedJobRecord,
  selectedJobRecordErrorMessage,
  isReplayingSelectedJob,
  replayErrorMessage,
  replaySuccessMessage,
  onReloadSelectedJobRecord,
  onReplaySelectedJob,
}: SelectedJobStatusProperties): ReactElement {
  const selectedJobStatus = selectedJobRecord?.status ?? "queued";

  return (
    <section className="dashboard-card dashboard-card--status" data-testid="selected-job-panel">
      <div className="section-heading section-heading--inline">
        <div>
          <p className="eyebrow">Selected job</p>
          <h2>Selected job signal</h2>
          <p className="section-copy section-copy--compact">Auto-refresh stays on until the job reaches a terminal state.</p>
        </div>
        <div className="toolbar-row">
          {selectedJobRecord?.status === "dead_lettered" ? (
            <button
              className="primary-button"
              data-testid="replay-job-button"
              type="button"
              disabled={isReplayingSelectedJob}
              onClick={() => void onReplaySelectedJob()}
            >
              {isReplayingSelectedJob ? "Replaying..." : "Replay job"}
            </button>
          ) : null}
          <button
            className="secondary-button"
            data-testid="selected-job-refresh-button"
            type="button"
            onClick={() => void onReloadSelectedJobRecord()}
          >
            Refresh now
          </button>
        </div>
      </div>

      {selectedJobIdentifier === null ? (
        <div className="empty-state">
          <h3>No job selected yet</h3>
          <p>Submit a new job or click one from the recent list to start tracking it here.</p>
        </div>
      ) : null}

      {selectedJobIdentifier !== null && selectedJobRecord === null && isLoadingSelectedJobRecord ? (
        <div className="empty-state">
          <h3>Loading job details</h3>
          <p>The dashboard is fetching the latest persisted state from the API.</p>
        </div>
      ) : null}

      {selectedJobRecordErrorMessage !== null ? (
        <p className="status-banner status-banner--error">{selectedJobRecordErrorMessage}</p>
      ) : null}

      {replayErrorMessage !== null ? (
        <p className="status-banner status-banner--error" data-testid="replay-error-message">{replayErrorMessage}</p>
      ) : null}

      {replaySuccessMessage !== null ? (
        <p className="status-banner status-banner--success" data-testid="replay-success-message">{replaySuccessMessage}</p>
      ) : null}

      {selectedJobRecord !== null ? (
        <>
          <div className="job-status-header">
            <div>
              <p className="detail-label">Job id</p>
              <p className="job-identifier" data-testid="selected-job-id">{selectedJobRecord.id}</p>
            </div>
            <span className={`status-pill status-pill--${selectedJobStatus}`} data-testid="selected-job-status">{selectedJobStatus}</span>
          </div>

          <div className="stats-grid">
            <article className="stat-tile">
              <p className="detail-label">Job type</p>
              <p data-testid="selected-job-type">{selectedJobRecord.job_type}</p>
            </article>
            <article className="stat-tile">
              <p className="detail-label">Attempts</p>
              <p data-testid="selected-job-attempts">
                {selectedJobRecord.attempt_count} / {selectedJobRecord.maximum_attempt_count}
              </p>
            </article>
            <article className="stat-tile">
              <p className="detail-label">Created</p>
              <p>{formatTimestamp(selectedJobRecord.created_at)}</p>
            </article>
            <article className="stat-tile">
              <p className="detail-label">Updated</p>
              <p>{formatTimestamp(selectedJobRecord.updated_at)}</p>
            </article>
          </div>

          <div className="detail-grid">
            <div className="detail-block detail-block--wide">
              <p className="detail-label">Input value</p>
              <pre data-testid="selected-job-input-value">{selectedJobRecord.input_value}</pre>
            </div>

            <div className="detail-block">
              <p className="detail-label">Result</p>
              <pre data-testid="selected-job-result">{selectedJobRecord.result ?? "Waiting for worker output"}</pre>
            </div>

            <div className="detail-block">
              <p className="detail-label">Failure message</p>
              <pre data-testid="selected-job-failure-message">{selectedJobRecord.error_message ?? "No failure recorded"}</pre>
            </div>

            {selectedJobRecord.replayed_from_job_id !== null ? (
              <div className="detail-block detail-block--wide">
                <p className="detail-label">Replayed from job</p>
                <pre data-testid="selected-job-replayed-from">{selectedJobRecord.replayed_from_job_id}</pre>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}
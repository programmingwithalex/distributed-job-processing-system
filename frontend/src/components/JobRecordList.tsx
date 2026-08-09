import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { listJobRecords } from "../services/jobsApi";
import type { JobStatus, JobStatusResponse } from "../types/jobs";


const availableStatusFilters: Array<JobStatus | "all"> = [
  "all",
  "queued",
  "processing",
  "completed",
  "failed",
  "dead_lettered",
];


export interface JobRecordListProperties {
  selectedJobIdentifier: string | null;
  refreshSequence: number;
  onSelectJobIdentifier: (jobIdentifier: string) => void;
}


/** Format a timestamp for compact table display. */
function formatCompactTimestamp(timestampValue: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestampValue));
}


/** Render the recent persisted jobs list with filtering and selection. */
export function JobRecordList({
  selectedJobIdentifier,
  refreshSequence,
  onSelectJobIdentifier,
}: JobRecordListProperties): ReactElement {
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [jobRecords, setJobRecords] = useState<JobStatusResponse[]>([]);
  const [isLoadingJobRecords, setIsLoadingJobRecords] = useState<boolean>(true);
  const [jobRecordListErrorMessage, setJobRecordListErrorMessage] = useState<string | null>(null);

  /** Load the recent persisted jobs from the backend API. */
  async function loadJobRecords(): Promise<void> {
    setIsLoadingJobRecords(true);

    try {
      const fetchedJobRecords = await listJobRecords({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: 12,
        offset: 0,
      });
      setJobRecords(fetchedJobRecords);
      setJobRecordListErrorMessage(null);
    } catch (jobListError) {
      const message = jobListError instanceof Error ? jobListError.message : "Failed to load recent jobs";
      setJobRecordListErrorMessage(message);
    } finally {
      setIsLoadingJobRecords(false);
    }
  }


  useEffect(() => {
    void loadJobRecords();
  }, [refreshSequence, statusFilter]);

  return (
    <section className="dashboard-card dashboard-card--list" data-testid="job-record-list-panel">
      <div className="section-heading section-heading--inline">
        <div>
          <p className="eyebrow">Recent jobs</p>
          <h2>Recent queue traffic</h2>
        </div>

        <div className="toolbar-row">
          <label className="field-group field-group--compact">
            <span>Status</span>
            <select
              className="text-input"
              data-testid="job-status-filter"
              value={statusFilter}
              onChange={(changeEvent) => setStatusFilter(changeEvent.target.value as JobStatus | "all")}
            >
              {availableStatusFilters.map((availableStatusFilter) => (
                <option key={availableStatusFilter} value={availableStatusFilter}>
                  {availableStatusFilter}
                </option>
              ))}
            </select>
          </label>

          <button
            className="secondary-button"
            data-testid="refresh-job-list-button"
            type="button"
            onClick={() => void loadJobRecords()}
          >
            Refresh list
          </button>
        </div>
      </div>

      {jobRecordListErrorMessage !== null ? <p className="status-banner status-banner--error">{jobRecordListErrorMessage}</p> : null}

      <div className="job-table-wrapper">
        <table className="job-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Type</th>
              <th>Input</th>
              <th>Attempts</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {isLoadingJobRecords ? (
              <tr>
                <td colSpan={5} className="table-empty-cell">
                  Loading recent jobs...
                </td>
              </tr>
            ) : null}

            {!isLoadingJobRecords && jobRecords.length === 0 ? (
              <tr>
                <td colSpan={5} className="table-empty-cell">
                  No jobs matched the current filter.
                </td>
              </tr>
            ) : null}

            {!isLoadingJobRecords
              ? jobRecords.map((jobRecord) => (
                  <tr
                    key={jobRecord.id}
                    data-testid={`job-row-${jobRecord.id}`}
                    className={selectedJobIdentifier === jobRecord.id ? "job-row job-row--selected" : "job-row"}
                    onClick={() => onSelectJobIdentifier(jobRecord.id)}
                  >
                    <td>
                      <span className={`status-pill status-pill--${jobRecord.status}`}>{jobRecord.status}</span>
                    </td>
                    <td>{jobRecord.job_type}</td>
                    <td className="job-table-input-cell">{jobRecord.input_value}</td>
                    <td>
                      {jobRecord.attempt_count} / {jobRecord.maximum_attempt_count}
                    </td>
                    <td>{formatCompactTimestamp(jobRecord.updated_at)}</td>
                  </tr>
                ))
              : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
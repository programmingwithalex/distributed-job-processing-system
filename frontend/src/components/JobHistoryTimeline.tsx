import type { ReactElement } from "react";

import type { JobLifecycleEventResponse, JobLifecycleEventType } from "../types/jobs";

const eventTypeLabels: Record<JobLifecycleEventType, string> = {
  submitted: "Submitted",
  processing: "Processing",
  retry_scheduled: "Retry scheduled",
  completed: "Completed",
  dead_lettered: "Dead-lettered",
  replayed: "Replayed",
};


/** Format an event timestamp for the selected-job timeline. */
function formatHistoryTimestamp(timestampValue: string): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestampValue));
}


export interface JobHistoryTimelineProperties {
  jobHistoryEvents: JobLifecycleEventResponse[];
  isLoadingJobHistory: boolean;
  jobHistoryErrorMessage: string | null;
}


/** Render the event-projected attempts and replay lineage for a selected job. */
export function JobHistoryTimeline({
  jobHistoryEvents,
  isLoadingJobHistory,
  jobHistoryErrorMessage,
}: JobHistoryTimelineProperties): ReactElement {
  return (
    <div className="detail-block detail-block--wide job-history-block" data-testid="job-history-timeline">
      <div className="job-history-heading">
        <p className="detail-label">Lifecycle history</p>
        <span>{jobHistoryEvents.length} events</span>
      </div>

      {jobHistoryErrorMessage !== null ? (
        <p className="status-banner status-banner--error" role="alert">{jobHistoryErrorMessage}</p>
      ) : null}

      {jobHistoryEvents.length === 0 ? (
        <p className="job-history-empty">
          {isLoadingJobHistory ? "Loading event history..." : "No lifecycle events have been projected yet."}
        </p>
      ) : (
        <ol className="job-history-list">
          {jobHistoryEvents.map((jobHistoryEvent) => (
            <li
              className="job-history-item"
              key={jobHistoryEvent.event_id}
              data-testid="job-history-event"
            >
              <div className="job-history-event-heading">
                <strong>
                  {jobHistoryEvent.sequence_number}. {eventTypeLabels[jobHistoryEvent.event_type]}
                </strong>
                <time dateTime={jobHistoryEvent.occurred_at}>
                  {formatHistoryTimestamp(jobHistoryEvent.occurred_at)}
                </time>
              </div>
              <p>
                {jobHistoryEvent.status} | attempt {jobHistoryEvent.attempt_count} / {jobHistoryEvent.maximum_attempt_count}
              </p>
              {jobHistoryEvent.error_message !== null ? (
                <p className="job-history-error">{jobHistoryEvent.error_message}</p>
              ) : null}
              {jobHistoryEvent.replayed_from_job_id !== null ? (
                <p className="job-history-lineage">
                  Replayed from <code>{jobHistoryEvent.replayed_from_job_id}</code>
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
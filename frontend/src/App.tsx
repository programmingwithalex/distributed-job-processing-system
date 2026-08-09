import { useState } from "react";
import type { ReactElement } from "react";

import { JobRecordList } from "./components/JobRecordList";
import { JobSubmissionForm } from "./components/JobSubmissionForm";
import { SelectedJobStatus } from "./components/SelectedJobStatus";
import { useSelectedJobRecord } from "./hooks/useSelectedJobRecord";
import { replayJobRecord } from "./services/jobsApi";
import type { JobStatusResponse } from "./types/jobs";


/** Render the top-level dashboard for job submission and monitoring. */
export function App(): ReactElement {
  const [selectedJobIdentifier, setSelectedJobIdentifier] = useState<string | null>(null);
  const [jobRecordListRefreshSequence, setJobRecordListRefreshSequence] = useState<number>(0);
  const [isReplayingSelectedJob, setIsReplayingSelectedJob] = useState<boolean>(false);
  const [replayErrorMessage, setReplayErrorMessage] = useState<string | null>(null);
  const [replaySuccessMessage, setReplaySuccessMessage] = useState<string | null>(null);
  const {
    selectedJobRecord,
    isLoadingSelectedJobRecord,
    selectedJobRecordErrorMessage,
    reloadSelectedJobRecord,
  } = useSelectedJobRecord(selectedJobIdentifier);

  /** Promote a newly created job into the dashboard focus state. */
  function handleCreatedJobRecord(jobStatusResponse: JobStatusResponse): void {
    setSelectedJobIdentifier(jobStatusResponse.id);
    setJobRecordListRefreshSequence((currentRefreshSequence) => currentRefreshSequence + 1);
  }


  /** Replay the selected dead-lettered job and focus the dashboard on its replacement. */
  async function handleReplaySelectedJob(): Promise<void> {
    if (selectedJobRecord?.status !== "dead_lettered") {
      return;
    }

    setIsReplayingSelectedJob(true);
    setReplayErrorMessage(null);
    setReplaySuccessMessage(null);

    try {
      const replayedJobRecord = await replayJobRecord(selectedJobRecord.id);
      handleCreatedJobRecord(replayedJobRecord);
      setReplaySuccessMessage(`Replay queued as ${replayedJobRecord.id}`);
    } catch (replayError) {
      const message = replayError instanceof Error ? replayError.message : "Failed to replay selected job";
      setReplayErrorMessage(message);
    } finally {
      setIsReplayingSelectedJob(false);
    }
  }


  /** Focus the dashboard on a selected row from the recent-jobs list. */
  function handleSelectedJobIdentifier(jobIdentifier: string): void {
    setSelectedJobIdentifier(jobIdentifier);
    setReplayErrorMessage(null);
    setReplaySuccessMessage(null);
  }


  return (
    <main className="application-shell">
      <section className="hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Distributed job processing system</p>
          <div className="hero-title-row">
            <h1>Queue desk</h1>
            <p className="hero-tag">fastapi + celery + postgres</p>
          </div>
          <p className="hero-summary">
            Dispatch work, monitor retry behavior, and inspect the latest queue traffic from one compact surface.
          </p>
        </div>

        <div className="hero-stat-strip">
          <article>
            <span>Job types</span>
            <strong>3</strong>
          </article>
          <article>
            <span>Retry states</span>
            <strong>5</strong>
          </article>
          <article>
            <span>Desk mode</span>
            <strong>Live poll</strong>
          </article>
        </div>
      </section>

      <section className="dashboard-grid">
        <JobSubmissionForm onJobCreated={handleCreatedJobRecord} />
        <SelectedJobStatus
          selectedJobIdentifier={selectedJobIdentifier}
          selectedJobRecord={selectedJobRecord}
          isLoadingSelectedJobRecord={isLoadingSelectedJobRecord}
          selectedJobRecordErrorMessage={selectedJobRecordErrorMessage}
          isReplayingSelectedJob={isReplayingSelectedJob}
          replayErrorMessage={replayErrorMessage}
          replaySuccessMessage={replaySuccessMessage}
          onReloadSelectedJobRecord={reloadSelectedJobRecord}
          onReplaySelectedJob={handleReplaySelectedJob}
        />
        <JobRecordList
          selectedJobIdentifier={selectedJobIdentifier}
          refreshSequence={jobRecordListRefreshSequence}
          onSelectJobIdentifier={handleSelectedJobIdentifier}
        />
      </section>
    </main>
  );
}
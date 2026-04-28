import { useState } from "react";
import type { ReactElement } from "react";

import { createJobRecord } from "../services/jobsApi";
import type { JobStatusResponse, JobType } from "../types/jobs";


const availableJobTypes: JobType[] = ["echo", "reverse", "uppercase"];


export interface JobSubmissionFormProperties {
  onJobCreated: (jobStatusResponse: JobStatusResponse) => void;
}


/** Render the job submission form and send new jobs to the backend API. */
export function JobSubmissionForm({ onJobCreated }: JobSubmissionFormProperties): ReactElement {
  const [inputValue, setInputValue] = useState<string>("portfolio-import");
  const [jobType, setJobType] = useState<JobType>("echo");
  const [maximumAttemptCount, setMaximumAttemptCount] = useState<string>("");
  const [isSubmittingJob, setIsSubmittingJob] = useState<boolean>(false);
  const [submissionErrorMessage, setSubmissionErrorMessage] = useState<string | null>(null);

  /** Submit the current job form values to the backend API. */
  async function handleJobSubmissionFormSubmit(formEvent: React.FormEvent<HTMLFormElement>): Promise<void> {
    formEvent.preventDefault();
    setIsSubmittingJob(true);
    setSubmissionErrorMessage(null);

    try {
      const createdJobRecord = await createJobRecord({
        input_value: inputValue,
        job_type: jobType,
        maximum_attempt_count:
          maximumAttemptCount.trim() === "" ? undefined : Number.parseInt(maximumAttemptCount, 10),
      });
      onJobCreated(createdJobRecord);
    } catch (jobSubmissionError) {
      const message =
        jobSubmissionError instanceof Error ? jobSubmissionError.message : "Failed to submit the new job";
      setSubmissionErrorMessage(message);
    } finally {
      setIsSubmittingJob(false);
    }
  }


  return (
    <section className="dashboard-card dashboard-card--accent" data-testid="job-submission-panel">
      <div className="section-heading">
        <p className="eyebrow">New job</p>
        <h2>Dispatch work</h2>
        <p className="section-copy section-copy--compact">
          Choose the payload, transform mode, and optional retry budget for a single queued run.
        </p>
      </div>

      <form className="job-form" data-testid="job-submission-form" onSubmit={handleJobSubmissionFormSubmit}>
        <label className="field-group">
          <span>Input value</span>
          <textarea
            className="text-input text-input--multiline"
            data-testid="job-input-value"
            value={inputValue}
            onChange={(changeEvent) => setInputValue(changeEvent.target.value)}
            maxLength={255}
            rows={3}
            required
          />
        </label>

        <div className="form-grid">
          <label className="field-group">
            <span>Job type</span>
            <select
              className="text-input"
              data-testid="job-type-select"
              value={jobType}
              onChange={(changeEvent) => setJobType(changeEvent.target.value as JobType)}
            >
              {availableJobTypes.map((availableJobType) => (
                <option key={availableJobType} value={availableJobType}>
                  {availableJobType}
                </option>
              ))}
            </select>
          </label>

          <label className="field-group">
            <span>Maximum attempts</span>
            <input
              className="text-input"
              data-testid="job-maximum-attempt-count"
              value={maximumAttemptCount}
              onChange={(changeEvent) => setMaximumAttemptCount(changeEvent.target.value)}
              inputMode="numeric"
              min={1}
              max={10}
              placeholder="Use backend default"
            />
          </label>
        </div>

        <div className="preset-row">
          <button
            className="preset-button"
            data-testid="preset-transient-failure"
            type="button"
            onClick={() => setInputValue("fail-once:portfolio-import")}
          >
            Try transient failure
          </button>
          <button
            className="preset-button"
            data-testid="preset-terminal-failure"
            type="button"
            onClick={() => setInputValue("always-fail:portfolio-import")}
          >
            Try terminal failure
          </button>
        </div>

        {submissionErrorMessage !== null ? <p className="status-banner status-banner--error">{submissionErrorMessage}</p> : null}

        <button
          className="primary-button"
          data-testid="submit-job-button"
          type="submit"
          disabled={isSubmittingJob || inputValue.trim() === ""}
        >
          {isSubmittingJob ? "Submitting job..." : "Submit job"}
        </button>
      </form>
    </section>
  );
}
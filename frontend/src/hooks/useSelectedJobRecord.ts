import { useEffect, useState } from "react";

import { fetchJobRecord } from "../services/jobsApi";
import type { JobStatus, JobStatusResponse } from "../types/jobs";


const terminalJobStatuses: JobStatus[] = ["completed", "failed", "dead_lettered"];
const pollingIntervalMilliseconds = 2500;


/** Return whether the selected job no longer needs polling. */
function isTerminalJobStatus(jobStatus: JobStatus | undefined): boolean {
  return jobStatus !== undefined && terminalJobStatuses.includes(jobStatus);
}


/** Return whether a thrown error was caused by an aborted fetch request. */
function isAbortError(unknownError: unknown): boolean {
  return unknownError instanceof DOMException && unknownError.name == "AbortError";
}


/** Poll and expose the currently selected job record. */
export function useSelectedJobRecord(selectedJobIdentifier: string | null): {
  selectedJobRecord: JobStatusResponse | null;
  isLoadingSelectedJobRecord: boolean;
  selectedJobRecordErrorMessage: string | null;
  reloadSelectedJobRecord: () => Promise<void>;
} {
  const [selectedJobRecord, setSelectedJobRecord] = useState<JobStatusResponse | null>(null);
  const [isLoadingSelectedJobRecord, setIsLoadingSelectedJobRecord] = useState<boolean>(false);
  const [selectedJobRecordErrorMessage, setSelectedJobRecordErrorMessage] = useState<string | null>(null);
  const [reloadSequence, setReloadSequence] = useState<number>(0);

  useEffect(() => {
    if (selectedJobIdentifier === null) {
      setSelectedJobRecord(null);
      setSelectedJobRecordErrorMessage(null);
      setIsLoadingSelectedJobRecord(false);
      return;
    }

    const stableSelectedJobIdentifier = selectedJobIdentifier;

    setSelectedJobRecord(null);
    setSelectedJobRecordErrorMessage(null);

    let isEffectActive = true;
    let activeAbortController: AbortController | null = null;
    let pollingTimer: number | null = null;

    async function loadSelectedJobRecord(showLoadingState: boolean): Promise<void> {
      activeAbortController?.abort();
      activeAbortController = new AbortController();

      if (showLoadingState) {
        setIsLoadingSelectedJobRecord(true);
      }

      try {
        const fetchedJobRecord = await fetchJobRecord(stableSelectedJobIdentifier, activeAbortController.signal);

        if (!isEffectActive) {
          return;
        }

        setSelectedJobRecord(fetchedJobRecord);
        setSelectedJobRecordErrorMessage(null);

        if (isTerminalJobStatus(fetchedJobRecord.status) && pollingTimer !== null) {
          window.clearInterval(pollingTimer);
          pollingTimer = null;
        }

        if (!isTerminalJobStatus(fetchedJobRecord.status) && pollingTimer === null) {
          pollingTimer = window.setInterval(() => {
            void loadSelectedJobRecord(false);
          }, pollingIntervalMilliseconds);
        }
      } catch (jobFetchError) {
        if (isAbortError(jobFetchError) || !isEffectActive) {
          return;
        }

        const message = jobFetchError instanceof Error ? jobFetchError.message : "Failed to load selected job";
        setSelectedJobRecordErrorMessage(message);
      } finally {
        if (showLoadingState && isEffectActive) {
          setIsLoadingSelectedJobRecord(false);
        }
      }
    }

    void loadSelectedJobRecord(true);

    return () => {
      isEffectActive = false;
      activeAbortController?.abort();

      if (pollingTimer !== null) {
        window.clearInterval(pollingTimer);
      }
    };
  }, [reloadSequence, selectedJobIdentifier]);

  return {
    selectedJobRecord,
    isLoadingSelectedJobRecord,
    selectedJobRecordErrorMessage,
    reloadSelectedJobRecord: async (): Promise<void> => {
      setReloadSequence((currentReloadSequence) => currentReloadSequence + 1);
    },
  };
}
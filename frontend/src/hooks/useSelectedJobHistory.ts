import { useEffect, useState } from "react";

import { fetchJobHistoryEvents } from "../services/jobsApi";
import type { JobLifecycleEventResponse } from "../types/jobs";

const historyPollingIntervalMilliseconds = 3000;


/** Return whether a failed fetch was caused by an aborted request. */
function isAbortError(unknownError: unknown): boolean {
  return unknownError instanceof DOMException && unknownError.name === "AbortError";
}


/** Poll and expose projected lifecycle events for the currently selected job. */
export function useSelectedJobHistory(selectedJobIdentifier: string | null): {
  jobHistoryEvents: JobLifecycleEventResponse[];
  isLoadingJobHistory: boolean;
  jobHistoryErrorMessage: string | null;
} {
  const [jobHistoryEvents, setJobHistoryEvents] = useState<JobLifecycleEventResponse[]>([]);
  const [isLoadingJobHistory, setIsLoadingJobHistory] = useState<boolean>(false);
  const [jobHistoryErrorMessage, setJobHistoryErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (selectedJobIdentifier === null) {
      setJobHistoryEvents([]);
      setIsLoadingJobHistory(false);
      setJobHistoryErrorMessage(null);
      return;
    }

    const stableSelectedJobIdentifier = selectedJobIdentifier;
    let isEffectActive = true;
    let isRequestInFlight = false;
    let activeAbortController: AbortController | null = null;

    setJobHistoryEvents([]);
    setIsLoadingJobHistory(true);
    setJobHistoryErrorMessage(null);

    async function loadJobHistory(showLoadingState: boolean): Promise<void> {
      if (isRequestInFlight) {
        return;
      }

      isRequestInFlight = true;
      activeAbortController = new AbortController();
      if (showLoadingState) {
        setIsLoadingJobHistory(true);
      }

      try {
        const fetchedJobHistory = await fetchJobHistoryEvents(
          stableSelectedJobIdentifier,
          activeAbortController.signal,
        );
        if (isEffectActive) {
          setJobHistoryEvents(fetchedJobHistory);
          setJobHistoryErrorMessage(null);
        }
      } catch (historyFetchError) {
        if (isEffectActive && !isAbortError(historyFetchError)) {
          const message = historyFetchError instanceof Error
            ? historyFetchError.message
            : "Failed to load job history";
          setJobHistoryErrorMessage(message);
        }
      } finally {
        isRequestInFlight = false;
        if (showLoadingState && isEffectActive) {
          setIsLoadingJobHistory(false);
        }
      }
    }

    void loadJobHistory(true);
    const pollingTimer = window.setInterval(() => {
      void loadJobHistory(false);
    }, historyPollingIntervalMilliseconds);

    return () => {
      isEffectActive = false;
      activeAbortController?.abort();
      window.clearInterval(pollingTimer);
    };
  }, [selectedJobIdentifier]);

  return {
    jobHistoryEvents,
    isLoadingJobHistory,
    jobHistoryErrorMessage,
  };
}
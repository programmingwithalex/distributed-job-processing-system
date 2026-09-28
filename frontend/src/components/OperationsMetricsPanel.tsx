import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { fetchOperationsMetrics } from "../services/jobsApi";
import type { OperationsMetricsResponse } from "../types/jobs";

const metricsPollingIntervalMilliseconds = 5000;
const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });


/** Format a metric number without introducing excess decimal places. */
function formatMetricValue(metricValue: number): string {
  return numberFormatter.format(metricValue);
}


/** Render live event-pipeline metrics from the operations endpoint. */
export function OperationsMetricsPanel(): ReactElement {
  const [operationsMetrics, setOperationsMetrics] = useState<OperationsMetricsResponse | null>(null);
  const [operationsMetricsError, setOperationsMetricsError] = useState<string | null>(null);
  const [isLoadingOperationsMetrics, setIsLoadingOperationsMetrics] = useState<boolean>(true);

  useEffect(() => {
    let isEffectActive = true;
    let isRequestInFlight = false;
    let activeAbortController: AbortController | null = null;

    async function loadOperationsMetrics(): Promise<void> {
      if (isRequestInFlight) {
        return;
      }

      isRequestInFlight = true;
      activeAbortController = new AbortController();
      try {
        const fetchedMetrics = await fetchOperationsMetrics(activeAbortController.signal);
        if (isEffectActive) {
          setOperationsMetrics(fetchedMetrics);
          setOperationsMetricsError(null);
        }
      } catch (metricsFetchError) {
        if (isEffectActive && !(metricsFetchError instanceof DOMException && metricsFetchError.name === "AbortError")) {
          const message = metricsFetchError instanceof Error
            ? metricsFetchError.message
            : "Failed to load operations metrics";
          setOperationsMetricsError(message);
        }
      } finally {
        isRequestInFlight = false;
        if (isEffectActive) {
          setIsLoadingOperationsMetrics(false);
        }
      }
    }

    void loadOperationsMetrics();
    const pollingTimer = window.setInterval(() => {
      void loadOperationsMetrics();
    }, metricsPollingIntervalMilliseconds);

    return () => {
      isEffectActive = false;
      activeAbortController?.abort();
      window.clearInterval(pollingTimer);
    };
  }, []);

  const metricsUpdatedAt = operationsMetrics === null
    ? null
    : new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })
      .format(new Date(operationsMetrics.sampled_at));

  return (
    <section className="operations-strip" aria-labelledby="operations-heading" data-testid="operations-metrics-panel">
      <div className="operations-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h2 id="operations-heading">Event pipeline</h2>
        </div>
        <p className="operations-window">
          {metricsUpdatedAt === null
            ? (isLoadingOperationsMetrics ? "Sampling metrics" : "No sample yet")
            : `Updated ${metricsUpdatedAt} · ${Math.round((operationsMetrics?.window_seconds ?? 0) / 60)} min window`}
        </p>
      </div>

      {operationsMetricsError !== null ? (
        <p className="status-banner status-banner--error" role="alert">{operationsMetricsError}</p>
      ) : null}

      <div className="operations-metrics-grid" aria-live="polite">
        <article className="operations-metric">
          <span>Completed / min</span>
          <strong data-testid="operations-throughput">
            {operationsMetrics === null ? "--" : formatMetricValue(operationsMetrics.throughput_jobs_per_minute)}
          </strong>
        </article>
        <article className="operations-metric">
          <span>Retry rate</span>
          <strong data-testid="operations-retry-rate">
            {operationsMetrics === null ? "--" : `${formatMetricValue(operationsMetrics.retry_rate_percent)}%`}
          </strong>
        </article>
        <article className="operations-metric">
          <span>Failure rate</span>
          <strong data-testid="operations-failure-rate">
            {operationsMetrics === null ? "--" : `${formatMetricValue(operationsMetrics.failure_rate_percent)}%`}
          </strong>
        </article>
        <article className="operations-metric">
          <span>Outbox backlog</span>
          <strong data-testid="operations-outbox-backlog">
            {operationsMetrics === null ? "--" : formatMetricValue(operationsMetrics.outbox_backlog)}
          </strong>
        </article>
        <article className="operations-metric">
          <span>Kafka consumer lag</span>
          <strong data-testid="operations-consumer-lag">
            {operationsMetrics === null ? "--" : formatMetricValue(operationsMetrics.kafka_consumer_lag)}
          </strong>
        </article>
      </div>
    </section>
  );
}
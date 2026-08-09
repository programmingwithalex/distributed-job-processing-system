import type { APIRequestContext, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";


const apiBaseUrl = process.env.PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8000";


interface CreatedJobRecord {
  id: string;
  input_value: string;
  job_type: string;
  status: string;
  replayed_from_job_id: string | null;
}


/** Return the recent-jobs refresh button with a resilient locator. */
function getRefreshJobListButton(page: Page) {
  return page.getByTestId("refresh-job-list-button").or(page.getByRole("button", { name: "Refresh list" }));
}


/** Return the recent-jobs row for a created job with a resilient locator. */
function getJobRow(page: Page, createdJobRecord: CreatedJobRecord) {
  return page
    .getByTestId(`job-row-${createdJobRecord.id}`)
    .or(page.locator("tr", { hasText: createdJobRecord.input_value }));
}


/** Return the selected-job panel locator. */
function getSelectedJobPanel(page: Page) {
  return page.getByTestId("selected-job-panel").or(page.locator(".dashboard-card--status"));
}


/** Create a job through the backend API for browser assertions. */
async function createJobRecordForTest(
  request: APIRequestContext,
  inputValue: string,
  jobType: "echo" | "reverse" | "uppercase",
): Promise<CreatedJobRecord> {
  const createJobResponse = await request.post(`${apiBaseUrl}/jobs`, {
    data: {
      input_value: inputValue,
      job_type: jobType,
      maximum_attempt_count: 1,
    },
  });

  expect(createJobResponse.ok()).toBeTruthy();
  return (await createJobResponse.json()) as CreatedJobRecord;
}


/** Wait for the backend to persist the requested terminal job status. */
async function waitForJobStatus(
  request: APIRequestContext,
  jobIdentifier: string,
  expectedStatus: string,
): Promise<CreatedJobRecord> {
  for (let attemptNumber = 0; attemptNumber < 20; attemptNumber += 1) {
    const jobStatusResponse = await request.get(`${apiBaseUrl}/jobs/${jobIdentifier}`);
    expect(jobStatusResponse.ok()).toBeTruthy();
    const jobRecord = (await jobStatusResponse.json()) as CreatedJobRecord;

    if (jobRecord.status === expectedStatus) {
      return jobRecord;
    }

    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error(`Job ${jobIdentifier} never reached status ${expectedStatus}`);
}


/** Wait for a specific job row to appear in the recent jobs list. */
async function expectJobRowToAppear(page: Page, createdJobRecord: CreatedJobRecord): Promise<void> {
  const jobRow = getJobRow(page, createdJobRecord);

  for (let attemptNumber = 0; attemptNumber < 4; attemptNumber += 1) {
    await getRefreshJobListButton(page).click();

    try {
      await expect(jobRow).toBeVisible({ timeout: 1500 });
      return;
    } catch {
      if (attemptNumber === 3) {
        throw new Error(`Job row ${createdJobRecord.id} never appeared in the recent jobs list`);
      }
    }
  }
}


test.describe("queue desk dashboard", () => {
  test("keeps the selected job panel locked to the clicked recent job", async ({ page, request }) => {
    const uniqueSuffix = `${Date.now()}-selection`;
    const firstCreatedJobRecord = await createJobRecordForTest(request, `always-fail:e2e-${uniqueSuffix}-a`, "echo");
    const secondCreatedJobRecord = await createJobRecordForTest(request, `always-fail:e2e-${uniqueSuffix}-b`, "reverse");

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Queue desk" })).toBeVisible();
    await expectJobRowToAppear(page, firstCreatedJobRecord);
    await expectJobRowToAppear(page, secondCreatedJobRecord);

    await getJobRow(page, secondCreatedJobRecord).click();

    const selectedJobPanel = getSelectedJobPanel(page);
    const selectedJobIdentifier = selectedJobPanel
      .getByTestId("selected-job-id")
      .or(selectedJobPanel.locator(".job-identifier"));
    const selectedJobInputValue = selectedJobPanel
      .getByTestId("selected-job-input-value")
      .or(selectedJobPanel.locator(".detail-block--wide pre"));
    const selectedJobType = selectedJobPanel
      .getByTestId("selected-job-type")
      .or(selectedJobPanel.locator(".stat-tile").nth(0).locator("p").nth(1));

    await expect(selectedJobIdentifier).toHaveText(secondCreatedJobRecord.id);
    await expect(selectedJobInputValue).toHaveText(secondCreatedJobRecord.input_value);
    await expect(selectedJobType).toHaveText(secondCreatedJobRecord.job_type);

    for (let assertionIndex = 0; assertionIndex < 8; assertionIndex += 1) {
      await page.waitForTimeout(400);
      await expect(selectedJobIdentifier).toHaveText(secondCreatedJobRecord.id);
      await expect(selectedJobInputValue).toHaveText(secondCreatedJobRecord.input_value);
      await expect(selectedJobType).toHaveText(secondCreatedJobRecord.job_type);
    }
  });

  test("submits a new job and focuses the selected job panel on the created record", async ({ page }) => {
    const uniqueSuffix = `${Date.now()}-submit`;
    const expectedInputValue = `always-fail:e2e-${uniqueSuffix}`;

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Queue desk" })).toBeVisible();

    await page.getByTestId("job-input-value").or(page.getByLabel("Input value")).fill(expectedInputValue);
    await page.getByTestId("job-type-select").or(page.getByLabel("Job type")).selectOption("uppercase");
    await page.getByTestId("job-maximum-attempt-count").or(page.getByLabel("Maximum attempts")).fill("1");
    await page.getByTestId("submit-job-button").or(page.getByRole("button", { name: "Submit job" })).click();

    const selectedJobPanel = getSelectedJobPanel(page);
    const selectedJobIdentifier = selectedJobPanel
      .getByTestId("selected-job-id")
      .or(selectedJobPanel.locator(".job-identifier"));
    const selectedJobInputValue = selectedJobPanel
      .getByTestId("selected-job-input-value")
      .or(selectedJobPanel.locator(".detail-block--wide pre"));
    const selectedJobType = selectedJobPanel
      .getByTestId("selected-job-type")
      .or(selectedJobPanel.locator(".stat-tile").nth(0).locator("p").nth(1));
    const selectedJobAttempts = selectedJobPanel
      .getByTestId("selected-job-attempts")
      .or(selectedJobPanel.locator(".stat-tile").nth(1).locator("p").nth(1));

    await expect(selectedJobIdentifier).not.toHaveText("", { timeout: 8000 });
    await expect(selectedJobInputValue).toHaveText(expectedInputValue);
    await expect(selectedJobType).toHaveText("uppercase");
    await expect(selectedJobAttempts).toHaveText(/0 \/ 1|1 \/ 1/);
  });

  test("replays a dead-lettered job and focuses the linked replacement", async ({ page, request }) => {
    const uniqueSuffix = `${Date.now()}-replay`;
    const deadLetteredJobRecord = await createJobRecordForTest(
      request,
      `always-fail:e2e-${uniqueSuffix}`,
      "echo",
    );
    await waitForJobStatus(request, deadLetteredJobRecord.id, "dead_lettered");

    await page.goto("/");
    await expectJobRowToAppear(page, deadLetteredJobRecord);
    await getJobRow(page, deadLetteredJobRecord).click();

    const selectedJobPanel = getSelectedJobPanel(page);
    await expect(selectedJobPanel.getByTestId("selected-job-status")).toHaveText("dead_lettered");
    const replayJobResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith(`/jobs/${deadLetteredJobRecord.id}/replay`),
    );
    await selectedJobPanel.getByTestId("replay-job-button").click();
    const replayedJobRecord = (await (await replayJobResponsePromise).json()) as CreatedJobRecord;

    await expect(selectedJobPanel.getByTestId("replay-success-message")).toContainText("Replay queued as");
    await expect(selectedJobPanel.getByTestId("selected-job-id")).toHaveText(replayedJobRecord.id);
    await expect(selectedJobPanel.getByTestId("selected-job-replayed-from")).toHaveText(
      deadLetteredJobRecord.id,
    );
  });
});
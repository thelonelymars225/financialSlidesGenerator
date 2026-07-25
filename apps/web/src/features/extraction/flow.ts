import type { ExtractionApi } from "./api";
import { isTerminalStatus } from "./state";
import type { CreateJobRequest, ExtractionJob, JobResult } from "./types";

type Wait = (milliseconds: number) => Promise<void>;

const defaultWait: Wait = (milliseconds) =>
  new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));

export async function waitForTerminalJob(
  api: ExtractionApi,
  jobId: string,
  options: { intervalMs?: number; maxPolls?: number; wait?: Wait } = {},
): Promise<ExtractionJob> {
  const intervalMs = options.intervalMs ?? 1_000;
  const maxPolls = options.maxPolls ?? 120;
  const wait = options.wait ?? defaultWait;

  for (let poll = 0; poll < maxPolls; poll += 1) {
    const job = await api.getJob(jobId);
    if (isTerminalStatus(job.status)) return job;
    await wait(intervalMs);
  }
  throw new Error("The extraction job did not finish within the polling limit.");
}

export async function submitPollAndLoad(
  api: ExtractionApi,
  request: CreateJobRequest,
  options: Parameters<typeof waitForTerminalJob>[2] = {},
): Promise<{ job: ExtractionJob; result?: JobResult }> {
  const created = await api.createJob(request);
  const job = await waitForTerminalJob(api, created.id, options);
  if (job.status !== "succeeded") return { job };
  return { job, result: await api.getResult(job.id) };
}

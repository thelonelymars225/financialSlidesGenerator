import type { GenerationApi } from "./api";
import { isTerminalGeneration } from "./state";
import type { GenerationJob, GenerationResult } from "./types";

type Wait = (milliseconds: number) => Promise<void>;

const defaultWait: Wait = (milliseconds) =>
  new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));

export async function waitForGeneration(
  api: GenerationApi,
  jobId: string,
  options: { intervalMs?: number; maxPolls?: number; wait?: Wait } = {},
): Promise<GenerationJob> {
  const wait = options.wait ?? defaultWait;
  for (let poll = 0; poll < (options.maxPolls ?? 120); poll += 1) {
    const job = await api.getJob(jobId);
    if (isTerminalGeneration(job.status)) return job;
    await wait(options.intervalMs ?? 1_000);
  }
  throw new Error("Slide generation did not finish within the polling limit.");
}

export async function generatePollAndLoad(
  api: GenerationApi,
  extractionJobId: string,
  deckType: Parameters<GenerationApi["start"]>[1],
  options: Parameters<typeof waitForGeneration>[2] = {},
): Promise<{ job: GenerationJob; result?: GenerationResult }> {
  const created = await api.start(extractionJobId, deckType);
  const job = await waitForGeneration(api, created.id, options);
  return job.status === "succeeded"
    ? { job, result: await api.getResult(job.id) }
    : { job };
}

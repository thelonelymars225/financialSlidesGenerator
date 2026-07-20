export type CreateJobRequest = {
  input_mode: "file" | "text";
  source_text?: string;
  file_name?: string;
  deck_purpose: string;
  slide_count: number;
};

export type Job = CreateJobRequest & {
  id: string;
  status: "queued";
};

export async function createJob(payload: CreateJobRequest): Promise<Job> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    throw new Error(problem?.detail ?? "The job could not be created.");
  }

  return response.json();
}

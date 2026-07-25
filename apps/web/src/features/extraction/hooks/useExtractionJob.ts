import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { extractionApi } from "../api";
import { nextPollInterval } from "../state";
import type { CreateJobRequest } from "../types";

export function useExtractionJob(jobId: string | null) {
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: (request: CreateJobRequest) => extractionApi.createJob(request),
  });

  const job = useQuery({
    queryKey: ["extraction-job", jobId],
    queryFn: () => extractionApi.getJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => nextPollInterval(query.state.data?.status),
  });

  const result = useQuery({
    queryKey: ["extraction-result", jobId],
    queryFn: () => extractionApi.getResult(jobId!),
    enabled: job.data?.status === "succeeded",
  });

  const cancel = useMutation({
    mutationFn: () => extractionApi.cancelJob(jobId!),
    onSuccess: (cancelledJob) => {
      queryClient.setQueryData(["extraction-job", jobId], cancelledJob);
    },
  });

  return { create, job, result, cancel };
}

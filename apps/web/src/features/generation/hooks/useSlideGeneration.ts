import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { DeckPurpose } from "../../extraction/types";
import { generationApi } from "../api";
import { generationPollInterval } from "../state";

export function useSlideGeneration() {
  const [jobId, setJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const start = useMutation({
    mutationFn: ({
      extractionJobId,
      deckType,
      requestKey,
    }: {
      extractionJobId: string;
      deckType: DeckPurpose;
      requestKey: string;
    }) => generationApi.start(extractionJobId, deckType, requestKey),
    onSuccess: (job) => setJobId(job.id),
  });

  const job = useQuery({
    queryKey: ["generation-job", jobId],
    queryFn: () => generationApi.getJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => generationPollInterval(query.state.data?.status),
  });

  const result = useQuery({
    queryKey: ["generation-result", jobId],
    queryFn: () => generationApi.getResult(jobId!),
    enabled: job.data?.status === "succeeded",
  });

  const retry = useMutation({
    mutationFn: () => generationApi.retry(jobId!),
    onSuccess: (queuedJob) => {
      queryClient.setQueryData(["generation-job", jobId], queuedJob);
    },
  });

  const download = useMutation({
    mutationFn: () => generationApi.download(jobId!),
  });

  return { start, job, result, retry, download };
}

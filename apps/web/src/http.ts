export type ApiErrorKind = "api" | "network" | "timeout" | "validation";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: ApiErrorKind,
    readonly status = 0,
    readonly code = "request_failed",
    readonly requestId?: string,
    errorName = "ApiError",
  ) {
    super(message);
    this.name = errorName;
  }
}

export const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
export const ARTIFACT_REQUEST_TIMEOUT_MS = 120_000;
const MAX_RETRIES = 2;

type Fetcher = typeof fetch;
type ResponseType = "json" | "blob";

interface RequestOptions extends Omit<RequestInit, "signal"> {
  responseType?: ResponseType;
  timeoutMs?: number;
  fallbackMessage?: string;
}

interface ApiProblem {
  detail?: string | Array<{ msg?: string }>;
  code?: string;
}

function problemMessage(problem: ApiProblem | null, fallbackMessage: string): string {
  if (Array.isArray(problem?.detail)) {
    return problem.detail.map((item) => item.msg).filter(Boolean).join("; ") || fallbackMessage;
  }
  return problem?.detail || fallbackMessage;
}

async function apiError(
  response: Response,
  fallbackMessage: string,
  errorName: string,
): Promise<ApiError> {
  const problem = await response.json().catch(() => null) as ApiProblem | null;
  return new ApiError(
    problemMessage(problem, fallbackMessage),
    response.status === 400 || response.status === 422 ? "validation" : "api",
    response.status,
    problem?.code,
    response.headers.get("X-Request-ID") || undefined,
    errorName,
  );
}

function isSafeMethod(method: string | undefined): boolean {
  const normalized = (method ?? "GET").toUpperCase();
  return normalized === "GET" || normalized === "HEAD";
}

export function createHttpClient(fetcher: Fetcher = fetch, errorName = "ApiError") {
  return async function request<T>(input: RequestInfo | URL, options: RequestOptions = {}): Promise<T> {
    const {
      responseType = "json",
      timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
      fallbackMessage = "The request could not be completed.",
      ...requestInit
    } = options;
    const canRetry = isSafeMethod(requestInit.method);

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
      const controller = new AbortController();
      const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetcher(input, { ...requestInit, signal: controller.signal });
        if (!response.ok) {
          if (canRetry && response.status >= 500 && attempt < MAX_RETRIES) continue;
          throw await apiError(response, fallbackMessage, errorName);
        }
        try {
          return (responseType === "blob" ? await response.blob() : await response.json()) as T;
        } catch {
          throw new ApiError(
            "The service returned an unexpected response. Please try again.",
            "validation",
            response.status,
            "invalid_response",
            response.headers.get("X-Request-ID") || undefined,
            errorName,
          );
        }
      } catch (error) {
        if (error instanceof ApiError) throw error;
        if (controller.signal.aborted) {
          throw new ApiError(
            "The request took too long. Please try again.",
            "timeout",
            0,
            "request_timeout",
            undefined,
            errorName,
          );
        }
        if (canRetry && attempt < MAX_RETRIES) continue;
        throw new ApiError(
          "The service could not be reached. Check your connection and try again.",
          "network",
          0,
          "network_error",
          undefined,
          errorName,
        );
      } finally {
        globalThis.clearTimeout(timeout);
      }
    }

    throw new ApiError(
      "The request could not be completed.",
      "network",
      0,
      "network_error",
      undefined,
      errorName,
    );
  };
}

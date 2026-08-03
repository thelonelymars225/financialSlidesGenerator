function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, "");
}

export function apiUrl(
  path: string,
  baseUrl = import.meta.env.VITE_API_BASE_URL ?? "",
): string {
  if (!path.startsWith("/")) throw new Error("API paths must start with /");
  const base = normalizeBaseUrl(baseUrl);
  return base ? `${base}${path}` : path;
}

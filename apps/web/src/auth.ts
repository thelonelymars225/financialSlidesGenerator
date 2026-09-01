import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL?.trim();
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();

export const supabase = supabaseUrl && publishableKey
  ? createClient(supabaseUrl, publishableKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    })
  : null;

export function setSelectedOrganization(organizationId: string): void {
  window.localStorage.setItem("financial-slides-organization-id", organizationId);
}

export async function apiAuthHeaders(ownerId = "local-development"): Promise<HeadersInit> {
  if (!supabase) return { "X-Owner-ID": ownerId };
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session) throw new Error("Sign in before accessing financial reports.");
  const organizationId = window.localStorage.getItem("financial-slides-organization-id");
  if (!organizationId) throw new Error("Select an organization before accessing reports.");
  return {
    Authorization: `Bearer ${data.session.access_token}`,
    "X-Organization-ID": organizationId,
  };
}

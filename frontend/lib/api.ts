import { CaseOption, CaseOverview, EvidenceRequest, Investigation, Ring } from "./types";

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
const apiKey = process.env.NEXT_PUBLIC_API_KEY;
const userRole = process.env.NEXT_PUBLIC_USER_ROLE;
const analystName = process.env.NEXT_PUBLIC_ANALYST_NAME?.trim();
const headers = () => ({ "content-type": "application/json", ...(apiKey ? { "x-api-key": apiKey } : {}), ...(userRole ? { "x-user-role": userRole } : {}) });
export type ApiHealth = { status: string; workflow_configured?: boolean; auth_enabled?: boolean };
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  if (!configuredBaseUrl) throw new Error("The investigation API is not configured. Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local.");
  let response: Response;
  try { response = await fetch(`${configuredBaseUrl}${path}`, { ...init, headers: { ...headers(), ...(init?.headers ?? {}) } }); }
  catch { throw new Error("The investigation API could not be reached. Confirm it is running and permits this frontend origin."); }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `The investigation API returned ${response.status}.`);
  }
  return response.json() as Promise<T>;
}
async function uploadCasePack(file: File): Promise<{ status: string; workflow_configured: boolean; case_count: number }> {
  if (!configuredBaseUrl) throw new Error("The investigation API is not configured. Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local.");
  let response: Response;
  try { response = await fetch(`${configuredBaseUrl}/setup/case-pack`, { method: "POST", headers: { ...(apiKey ? { "x-api-key": apiKey } : {}) }, body: await file.text() }); }
  catch { throw new Error("The investigation API could not be reached. Confirm it is running and permits this frontend origin."); }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `The investigation API returned ${response.status}.`);
  }
  return response.json() as Promise<{ status: string; workflow_configured: boolean; case_count: number }>;
}
export const api = {
  isConfigured: Boolean(configuredBaseUrl),
  identity: { name: analystName || "", role: userRole || "" },
  health: () => call<ApiHealth>("/health", { headers: { accept: "application/json" } }),
  uploadCasePack,
  cases: () => call<CaseOption[]>("/cases"),
  overview: () => call<CaseOverview[]>("/cases/overview"),
  rings: () => call<Ring[]>("/network/rings?min_customers=3&top_k=8"),
  start: (caseId: string) => call<Investigation>("/investigations/start", { method: "POST", body: JSON.stringify({ case_id: caseId }) }),
  state: (caseId: string) => call<Investigation>(`/investigations/${caseId}`),
  approve: (caseId: string, action: string, approved: boolean) => call<Investigation>(`/investigations/${caseId}/approval`, { method: "POST", body: JSON.stringify({ action, approved }) }),
  evidence: (caseId: string, request: EvidenceRequest, result: string, details: string) => call<Investigation>(`/investigations/${caseId}/evidence`, { method: "POST", body: JSON.stringify({ evidence: { request_id: request.request_id, case_id: caseId, type: request.type, result, details, source: request.type === "customer_validation" ? "customer" : request.type === "step_up_auth" ? "step_up_auth" : "analyst" } }) }),
};

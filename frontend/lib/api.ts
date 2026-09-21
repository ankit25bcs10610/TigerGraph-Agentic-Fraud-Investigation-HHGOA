import { CaseOption, EvidenceRequest, Investigation } from "./types";

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
const apiKey = process.env.NEXT_PUBLIC_API_KEY;
const userRole = process.env.NEXT_PUBLIC_USER_ROLE;
const headers = () => ({ "content-type": "application/json", ...(apiKey ? { "x-api-key": apiKey } : {}), ...(userRole ? { "x-user-role": userRole } : {}) });
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  if (!configuredBaseUrl) throw new Error("The investigation API is not configured. Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local.");
  let response: Response;
  try { response = await fetch(`${configuredBaseUrl}${path}`, { ...init, headers: { ...headers(), ...(init?.headers ?? {}) } }); }
  catch { throw new Error("The investigation API could not be reached. Confirm it is running and permits this frontend origin."); }
  if (!response.ok) throw new Error((await response.text().catch(() => "")) || `The investigation API returned ${response.status}.`);
  return response.json() as Promise<T>;
}
export const api = {
  isConfigured: Boolean(configuredBaseUrl),
  cases: () => call<CaseOption[]>("/cases"),
  start: (caseId: string) => call<Investigation>("/investigations/start", { method: "POST", body: JSON.stringify({ case_id: caseId }) }),
  approve: (caseId: string, action: string, approved: boolean) => call<Investigation>(`/investigations/${caseId}/approval`, { method: "POST", body: JSON.stringify({ action, approved }) }),
  evidence: (caseId: string, request: EvidenceRequest, result: string, details: string) => call<Investigation>(`/investigations/${caseId}/evidence`, { method: "POST", body: JSON.stringify({ evidence: { request_id: request.request_id, case_id: caseId, type: request.type, result, details, source: request.type === "customer_validation" ? "customer" : request.type === "step_up_auth" ? "step_up_auth" : "analyst" } }) }),
};

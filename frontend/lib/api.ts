import { Investigation } from "./types";

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  if (!configuredBaseUrl) {
    throw new Error("The investigation API is not configured. Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local, then restart the frontend.");
  }
  let response: Response;
  try {
    response = await fetch(`${configuredBaseUrl}${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new Error("The investigation API could not be reached. Confirm it is running and permits this frontend origin.");
  }
  if (!response.ok) throw new Error((await response.text().catch(() => "")) || `The investigation API returned ${response.status}.`);
  return response.json() as Promise<T>;
}

export const api = {
  isConfigured: Boolean(configuredBaseUrl),
  start: (caseId: string) => call<Investigation>("/investigations/start", { method: "POST", body: JSON.stringify({ case_id: caseId }) }),
  approve: (caseId: string, action: string, approved: boolean) => call<Investigation>(`/investigations/${caseId}/approval`, { method: "POST", body: JSON.stringify({ action, approved }) }),
};

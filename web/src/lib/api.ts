import type {
  AuditRecord,
  EvaluationResult,
  Metrics,
  PolicyVersions,
  PolicyView,
  Scenario,
} from "@/types/api";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...JSON_HEADERS, ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? "Request failed");
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),
  scenarios: () => request<Scenario[]>("/api/scenarios"),
  runScenario: (id: string) =>
    request<EvaluationResult>(`/api/scenarios/${id}/run`, { method: "POST" }),
  metrics: () => request<Metrics>("/api/metrics"),
  policies: () => request<PolicyView[]>("/api/policies"),
  policyVersions: () => request<PolicyVersions>("/api/policies/versions"),
  audits: (limit = 10) => request<AuditRecord[]>(`/api/audits?limit=${limit}`),
  runEvaluationSuite: () =>
    request<{ count: number; metrics: Metrics }>("/api/evaluation-suite/run", {
      method: "POST",
    }),
  review: (auditId: string, humanLabel: "safe" | "unsafe") =>
    request<{ audit_id: string }>(`/api/audits/${auditId}/review`, {
      method: "POST",
      body: JSON.stringify({
        human_label: humanLabel,
        note: "Submitted from Next.js dashboard",
      }),
    }),
};

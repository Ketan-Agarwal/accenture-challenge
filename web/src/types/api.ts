export type Decision = "allow" | "warn_or_edit" | "hold_for_human" | "block";

export type Scenario = {
  id: string;
  title: string;
  description: string;
  use_case: string;
  region: string;
  action: string;
  session_id: string;
  prompt: string;
  proposed_response?: string;
  samples?: string[];
  expected_decision: Decision;
  expected_harmful?: boolean;
  prior_session_risk?: number;
};

export type EvidenceSignal = {
  check_id: string;
  code: string;
  labels: string[];
  severity: number;
  confidence: number;
  status: string;
  summary: string;
  evidence: string[];
  limitations?: string;
  latency_ms?: number;
};

export type PolicyView = {
  profile: string;
  owner: string;
  version: string;
  requested_version?: string | null;
  version_stale?: boolean;
  region: string;
  region_label: string;
  risk_appetite: string;
  latency_budget_ms: number;
  permitted_actions: string[];
  checks: string[];
  retention_days: number;
  consent_required: boolean;
  pii_categories: string[];
};

export type EvaluationResult = {
  audit_id: string;
  scenario_id?: string | null;
  use_case: string;
  region: string;
  action: string;
  session_id: string;
  blast_radius: string;
  policy: PolicyView;
  decision: Decision;
  risk_score: number;
  reason_codes: string[];
  signals: EvidenceSignal[];
  original_response?: string | null;
  safe_response?: string | null;
  model_called: boolean;
  total_latency_ms: number;
  check_cost: {
    model_calls: number;
    primary_model_calls: number;
    verification_sample_calls: number;
    checks_run: string[];
    blast_radius?: string;
  };
  decision_summary: string;
};

export type Metrics = {
  volume: number;
  decisions: Record<Decision, number>;
  intervention_rate: number | null;
  reviewed: number;
  override_rate: number | null;
  model_calls: number;
  verification_sample_calls_by_radius: Record<string, number>;
  latency_ms: { median: number | null; p95: number | null };
  confusion_matrix: { tp: number; fp: number; fn: number; tn: number; labeled: number };
  precision: number | null;
  recall: number | null;
  false_positive_rate: number | null;
  false_negative_rate: number | null;
  by_profile: Record<string, { total: number; interventions: number }>;
  metric_note: string;
};

export type PolicyVersions = {
  schema_version: string;
  active_version: string;
  version_history: string[];
  superseded_versions: string[];
  profiles: string[];
  regions: string[];
};

export type AuditRecord = {
  audit_id: string;
  created_at: string;
  scenario_id?: string | null;
  use_case: string;
  region: string;
  action: string;
  blast_radius: string;
  decision: Decision;
  risk_score: number;
  policy_version: string;
  reason_codes: string[];
  latency_ms: number;
  decision_summary?: string;
};

export type CommerceOrder = {
  order_id: string;
  item: string;
  order_total_inr: number;
  status: string;
  fulfilment_issue?: string | null;
  refund_status?: string | null;
  refunded_amount_inr?: number | null;
};

export type GovernedAction = {
  action_id: string;
  order_id: string;
  use_case: string;
  region: string;
  session_id: string;
  amount_inr: number;
  reason: string;
  audit_id?: string;
  decision: Decision;
  status: string;
  authorization_token?: string | null;
  risk_score?: number;
  reason_codes?: string[];
  signals?: EvidenceSignal[];
  decision_summary?: string;
  policy_version?: string;
  token_expires_at?: string | null;
  created_at?: string;
  reviewed_at?: string | null;
  executed_at?: string | null;
  review_note?: string | null;
};

export type ActionProposal = {
  action: GovernedAction;
  evaluation?: EvaluationResult;
  authorization_token?: string | null;
};

export type PolicySimulationRow = {
  profile: string;
  region: string;
  decision: Decision;
  risk_score: number;
  reason_codes: string[];
  decision_summary: string;
  blast_radius?: string;
  policy_version?: string;
  thresholds?: Record<string, number>;
  checks_run?: string[];
};

export type PolicySimulation = {
  results: PolicySimulationRow[];
};

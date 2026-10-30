// Talks to the backend. Every call sends the API key from local storage.

export type Requirement = { id: string; text: string; must_have: boolean };

export type RoleSummary = {
  id: string;
  title: string;
  company: string;
  location: string;
  shortlist_size: number;
};

export type LatestScreening = { run_id: string; status: string; updated_at: string } | null;

export type CandidateRow = {
  id: string;
  full_name: string;
  headline: string;
  location: string;
  current_title: string | null;
  current_company: string | null;
  years_of_experience: number;
  is_stale: boolean;
  data_warnings: string[];
  latest_screening: LatestScreening;
};

export type Role = RoleSummary & {
  description: string;
  requirements: Requirement[];
  outreach: { sender_name: string; sender_title: string; max_chars: number };
  candidates: CandidateRow[];
};

export type RequirementScore = {
  requirement_id: string;
  score: number;
  reason: string;
  proof: string;
};

export type Scorecard = {
  scores: RequirementScore[];
  recommend: boolean;
  confidence: "high" | "medium" | "low";
  summary: string;
  warnings: string[];
};

export type RuleResult = { rule: string; passed: boolean; detail: string };

export type StepSummary = {
  seq: number;
  name: string;
  status: string;
  started_at: string;
  ms: number;
  tokens_in: number;
  tokens_out: number;
};

export type Step = StepSummary & { details: Record<string, unknown> };

export type Screening = {
  run_id: string;
  role_id: string;
  role_title: string;
  candidate_id: string;
  candidate_name: string;
  status: string;
  started_by: string;
  scorecard: Scorecard | null;
  draft_message: string | null;
  final_message: string | null;
  decision: { action: string; decided_by: string; decided_at: string } | null;
  send_receipt: { message_id: string; sent_at: string; attempts: number } | null;
  rule_results: RuleResult[];
  data_warnings: string[];
  error: string | null;
  tokens_in: number;
  tokens_out: number;
  created_at: string;
  updated_at: string;
  requirements: Requirement[];
  steps: StepSummary[];
};

export type AuditEntry = { at: string; actor: string; action: string; detail: string };
export type Trace = { run_id: string; steps: Step[]; audit: AuditEntry[] };
export type DataChecks = { errors: number; warnings: number };

const KEY_STORAGE = "sourcing-copilot-api-key";

// Development keys. Real deployments set the keys in the backend's environment and
// hand them out separately; the UI only ever stores what the user pasted in.
export const SIGN_IN_OPTIONS = [
  { label: "Recruiter", key: import.meta.env.VITE_RECRUITER_KEY ?? "recruiter-dev-key" },
  { label: "Viewer", key: import.meta.env.VITE_VIEWER_KEY ?? "viewer-dev-key" },
];

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) ?? SIGN_IN_OPTIONS[0].key;
}

export function setApiKey(key: string): void {
  localStorage.setItem(KEY_STORAGE, key);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": getApiKey(),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = (await response.json()).detail;
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  roles: () => request<RoleSummary[]>("/api/roles"),
  role: (roleId: string) => request<Role>(`/api/roles/${roleId}`),
  dataChecks: () => request<DataChecks>("/api/data-checks"),
  startScreening: (roleId: string, candidateId: string) =>
    request<Screening>(`/api/roles/${roleId}/screenings`, {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId }),
    }),
  screening: (runId: string) => request<Screening>(`/api/screenings/${runId}`),
  trace: (runId: string) => request<Trace>(`/api/screenings/${runId}/steps`),
  decide: (runId: string, action: "approve" | "reject", message?: string) =>
    request<Screening>(`/api/screenings/${runId}/decision`, {
      method: "POST",
      body: JSON.stringify({ action, message: message ?? null }),
    }),
};

export const STATUS_LABELS: Record<string, string> = {
  screening: "Screening",
  awaiting_approval: "Waiting for approval",
  sent: "Sent",
  rejected: "Rejected",
  not_recommended: "Not recommended",
  do_not_contact: "Do not contact",
  needs_review: "Needs review",
  failed: "Failed",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.detail as { message?: string; rules?: RuleResult[] } | string;
    if (typeof d === "object" && d && "rules" in d && d.rules) {
      return `${d.message}: ${d.rules.map((r) => `${r.rule} (${r.detail})`).join("; ")}`;
    }
    if (typeof d === "object" && d && "message" in d) return String(d.message);
    return String(err.message);
  }
  return err instanceof Error ? err.message : String(err);
}

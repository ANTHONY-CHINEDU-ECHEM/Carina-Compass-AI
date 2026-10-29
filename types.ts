export interface PatientContext {
  histology?: string;
  stage_group?: string;
  biomarkers: string[];
  pdl1_tps?: number;
  performance_status?: number;
  age?: number;
  sex?: string;
  weight_kg?: number;
  height_cm?: number;
  serum_creatinine_umol_l?: number;
  setting?: string;
  prior_treatments: string[];
  current_medicines: string[];
  conditions: string[];
  allergies: string[];
}

export interface Emergency {
  category: string;
  title: string;
  actions: string[];
  guidance: string[];
}

export interface ToolCard {
  tool: string;
  title: string;
  status: "ok" | "needs_input" | "error";
  result: Record<string, unknown> | null;
  missing: string[];
  message: string | null;
}

export interface Source {
  id: number;
  chunk_id: string;
  title: string;
  section: string | null;
  url: string;
  source: string;
  evidence_grade: number;
  evidence_label: string;
  year: number | null;
  jurisdiction: string;
  licence: string;
  superseded_by: string | null;
  score: number;
  excerpt: string;
}

export interface FinalResult {
  request_id: string;
  answer: string;
  status: "answered" | "abstained" | "out_of_scope" | "emergency_only";
  provider: string | null;
  model: string | null;
  fallbacks_used: string[];
  grounded: boolean;
  latency_ms: number;
  cached: boolean;
  citation_report: { coverage: number; unsupported_figures: string[] } | null;
  faithfulness: { claim_support: number } | null;
  redactions: Record<string, number>;
  sources: Source[];
}

export interface TherapyOption {
  option_id: string;
  regimen: string;
  nice_reference: string;
  nice_status: string;
  nice_status_label: string;
  guideline: string | null;
  evidence_trial: string | null;
  evidence_url: string | null;
  nice_url: string | null;
  notes: string | null;
  caveats: string[];
}

export interface TrialMatch {
  nct_id: string;
  title: string;
  url: string;
  status: string;
  status_verified: boolean;
  phases: string[];
  reasons: string[];
  cautions: string[];
}

export interface SafetyFlag {
  rule_id: string;
  severity: string;
  planned: string;
  trigger: string;
  message: string;
  source: string;
}

export interface DoseStep {
  calculation: string;
  value: number;
  unit: string;
  working: string[];
  warnings: string[];
}

export type Provider = "anthropic" | "openai" | "ollama" | "extractive";

export type ProjectSummary = {
  id: string;
  title: string;
  created_at: string;
  format_version: number;
};

export type ParentEdge = {
  parent_id: string;
  relationship: string;
  run_id: string | null;
};

export type Revision = {
  id: string;
  text: string;
  text_sha256: string;
  origin_kind: string;
  source_id: string | null;
  created_at: string;
  disposition: string | null;
  parents: ParentEdge[];
};

export type Annotation = {
  id: string;
  revision_id: string;
  kind: string;
  value: string;
  text_sha256: string;
};

export type Frame = {
  level: number;
  revision_id: string;
  text: string;
  raw_token_ids?: number[];
};

export type Candidate = {
  index: number;
  seed: number;
  prediction_count: number;
  revision_id: string;
  representation_id?: string;
  text: string;
};

export type Job = {
  id: string;
  operation: string;
  state: string;
  progress: {
    stage?: string;
    level?: number;
    level_count?: number;
    candidate?: number;
    candidate_count?: number;
  };
  request: {
    retained_level_count?: number;
    candidate_count?: number;
    base_seed?: number;
    passage_revision_id?: string;
    sampling?: { temperature: number; top_k: number; top_p: number };
  };
  result: {
    frames?: Frame[];
    candidates?: Candidate[];
    passage_revision_id?: string;
  } | null;
  error: { code?: string; message?: string } | null;
};

export type Desk = {
  project: { id: string; title: string; format_version: number };
  draft: { text: string; base_revision_id: string | null };
  selected_revision_id: string | null;
  revisions: Revision[];
  annotations: Annotation[];
  latest_job: Job | null;
  reconstruction: Job | null;
  variations: Job | null;
};

export type Status = {
  app_version: string;
  project_id: string | null;
  project_error?: { code: string; message: string } | null;
  worker: string;
  worker_error: string | null;
  capabilities?: {
    ncm?: { profile: string; state: string; message: string | null };
    embedding?: { profile: string; state: string; message: string | null };
  };
  live?: LiveState;
  model_profile: string;
  execution_profile: string;
};

export type LiveState = { profile: string; state: "unloaded" | "ready" | "unavailable"; message: string | null };

export type Layout = {
  levels: number[];
  codebook_sizes: number[];
  text_length: number;
  model_profile: string;
  execution_profile: string;
  display_policy: string;
};

export type TraceFrame = { level: number; text: string; raw_token_ids: number[] };

export type Trace = Layout & {
  text: string;
  token_count: number;
  padded_token_ids: number[];
  codes: number[];
  frames: TraceFrame[];
  ms: number;
};

export type Variation = {
  text: string;
  codes: number[];
  raw_token_ids: number[];
  changed: string;
  keep: number;
  seed: number;
  prediction_count: number;
  sampling: { temperature: number; top_k: number; top_p: number };
  source_codes: number[];
  source_text: string | null;
  source_token_count: number | null;
  source_padded_token_ids: number[] | null;
  trimmed: boolean;
  ms: number;
};

export function randomSeed(): number {
  const buffer = new Uint32Array(1);
  crypto.getRandomValues(buffer);
  return buffer[0];
}

export function variationBody(variation: Variation) {
  return {
    text: variation.text,
    codes: variation.codes,
    raw_token_ids: variation.raw_token_ids,
    keep: variation.keep,
    seed: variation.seed,
    sampling: variation.sampling,
  };
}

export type TokenCount = {
  token_count: number;
  text_length: number;
  too_long: boolean;
  policy: string;
};

export type RunRecord = {
  id: string;
  operation: string;
  parameters: {
    retained_level_count?: number | null;
    base_seed?: number | null;
    display_policy?: string;
    sampling?: { temperature: number; top_k: number; top_p: number } | null;
    donor?: { owner_kind: string; owner_id: string; start_byte: number; end_byte: number };
    host_revision_id?: string;
  };
};

export type History = {
  revision: Revision;
  run: RunRecord | null;
  runs?: { parent_id: string; relationship: string; run: RunRecord }[];
  annotations: Annotation[];
};

export class ApiError extends Error {
  code: string;
  constructor(message: string, code = "ERROR") {
    super(message);
    this.code = code;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(typeof init?.body === "string" ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(body?.message || response.statusText, body?.code || "ERROR");
  }
  return body as T;
}

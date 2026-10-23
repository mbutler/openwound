import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  type Annotation,
  type Candidate,
  type Desk,
  type History,
  type Job,
  type ProjectSummary,
  type Revision,
  type Status,
  type TokenCount,
} from "./api";
import { Correspondences } from "./Correspondences";
import { wordDiff } from "./diff";

const ACTIVE = new Set(["queued", "running"]);

function recordedRuns(history: History) {
  const distinct = new Map<string, NonNullable<History["run"]>>();
  for (const item of history.runs ?? []) {
    if (item.run) distinct.set(item.run.id, item.run);
  }
  return [...distinct.values()];
}

function workerLabel(status: Status | null): string {
  if (!status) return "Checking the worker.";
  if (status.worker === "starting") return "Starting the worker.";
  if (status.worker === "running") return "Working on the current passage.";
  if (status.worker === "ready") {
    const checkpoint = status.capabilities?.ncm;
    if (checkpoint?.state === "ready") return "Checkpoint ready.";
    if (checkpoint?.state === "unavailable") {
      return checkpoint.message || "The TinyStories checkpoint is not available.";
    }
    return "Worker ready. The checkpoint loads when a passage is encoded.";
  }
  if (status.worker_error) return status.worker_error;
  return "The inference worker is stopped.";
}

function progressLabel(job: Job): string {
  const progress = job.progress || {};
  if (job.state === "queued") return "Queued.";
  if (job.state === "succeeded") return "Finished.";
  if (job.state === "cancelled") return "Cancelled. Passages already written are kept.";
  if (job.state === "interrupted") return job.error?.message || "Interrupted.";
  if (job.state === "failed") return job.error?.message || "The job failed.";
  if (progress.stage === "encode") return "Encoding the passage.";
  if (progress.stage === "reconstruct") {
    return `Level ${progress.level ?? 0} of ${progress.level_count ?? 12}.`;
  }
  if (progress.stage === "generate") {
    return `Candidate ${progress.candidate ?? 0} of ${progress.candidate_count ?? 0}, level ${progress.level ?? 0} of ${progress.level_count ?? 12}.`;
  }
  return job.state;
}

function varyCaption(retained: number): string {
  if (retained === 0) return "A fresh unconditional story.";
  if (retained === 12) return "The encoded passage, with nothing sampled past the twelfth level.";
  return `Keep the first ${retained} ${retained === 1 ? "level" : "levels"}, then sample the rest.`;
}

function passageText(text: string): string {
  return text === "" ? "Empty display." : text;
}

export function App() {
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const loadedFor = useRef<string | null>(null);
  const projectRef = useRef<string | null>(null);
  const wasActive = useRef(false);
  const announced = useRef(new Set<string>());

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [desk, setDesk] = useState<Desk | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState("");
  const [tokens, setTokens] = useState<TokenCount | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [place, setPlace] = useState<"desk" | "correspondences">("desk");
  const [title, setTitle] = useState("");
  const [archive, setArchive] = useState<File | null>(null);
  const [retained, setRetained] = useState(3);
  const [advanced, setAdvanced] = useState(false);
  const [temperature, setTemperature] = useState("1");
  const [topK, setTopK] = useState("0");
  const [topP, setTopP] = useState("1");
  const [seedText, setSeedText] = useState("");
  const [candidateCount, setCandidateCount] = useState(4);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [history, setHistory] = useState<History | null>(null);
  const [note, setNote] = useState("");
  const [tag, setTag] = useState("");
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [comparingId, setComparingId] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [frameMs, setFrameMs] = useState(800);
  const [showOriginal, setShowOriginal] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);

  projectRef.current = desk?.project.id ?? null;
  const jobActive = job ? ACTIVE.has(job.state) : false;
  const frames = desk?.reconstruction?.result?.frames ?? [];
  const incomingVariants = job?.operation === "variants" ? job : null;
  const variationJob =
    incomingVariants &&
    ((incomingVariants.result?.candidates?.length ?? 0) > 0 || ACTIVE.has(incomingVariants.state))
      ? incomingVariants
      : (desk?.variations ?? null);
  const candidates = variationJob?.result?.candidates ?? [];
  const selected = desk?.revisions.find((item) => item.id === desk.selected_revision_id) ?? null;

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduceMotion(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  async function reloadDesk(projectId: string | null) {
    if (!projectId) {
      setDesk(null);
      return;
    }
    const next = await api<Desk>("/api/v1/desk");
    setDesk(next);
    if (loadedFor.current !== next.project.id) {
      loadedFor.current = next.project.id;
      setDraft(next.draft.text);
      setJob(next.latest_job);
      setFrameIndex(0);
      setPlaying(false);
      if (editorRef.current) editorRef.current.value = next.draft.text;
    } else {
      setDesk(next);
    }
  }

  async function reload() {
    const [listed, current] = await Promise.all([
      api<{ projects: ProjectSummary[]; active_project_id: string | null }>("/api/v1/projects"),
      api<Status>("/api/v1/status"),
    ]);
    setProjects(listed.projects);
    setStatus(current);
    await reloadDesk(current.project_id);
  }

  useEffect(() => {
    void reload().catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void api<Status>("/api/v1/status")
        .then(setStatus)
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!desk) return;
    const projectId = desk.project.id;
    const handle = window.setTimeout(() => {
      if (projectRef.current !== projectId) return;
      void api("/api/v1/draft", { method: "PUT", body: JSON.stringify({ text: draft }) }).catch(
        (reason: Error) => setError(reason.message),
      );
      void api<TokenCount>("/api/v1/tokenize-preview", {
        method: "POST",
        body: JSON.stringify({ text: draft }),
      })
        .then((counted) => {
          if (projectRef.current === projectId) setTokens(counted);
        })
        .catch((reason: Error) => setError(reason.message));
    }, 300);
    return () => window.clearTimeout(handle);
  }, [draft, desk?.project.id]);

  useEffect(() => {
    if (!job || !ACTIVE.has(job.state)) return;
    const timer = window.setInterval(() => {
      void api<Job>(`/api/v1/jobs/${job.id}`)
        .then(setJob)
        .catch((reason: Error) => setError(reason.message));
    }, 700);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.state]);

  useEffect(() => {
    if (!job) return;
    const active = ACTIVE.has(job.state);
    if (active) {
      wasActive.current = true;
      return;
    }
    if (!wasActive.current || announced.current.has(job.id)) return;
    announced.current.add(job.id);
    wasActive.current = false;
    if (job.state === "succeeded") {
      const ready =
        job.operation === "reconstruct" ? "The reconstruction is ready." : "The variations are ready.";
      setNotice(`${ready} Adoption stays a separate step.`);
    } else if (job.state === "cancelled") {
      setNotice("Cancelled. Passages already written are kept.");
    } else {
      setNotice(job.error?.message || "The job stopped.");
    }
    void api<Desk>("/api/v1/desk")
      .then(setDesk)
      .catch((reason: Error) => setError(reason.message));
  }, [job]);

  useEffect(() => {
    setFrameIndex(0);
    setPlaying(false);
  }, [desk?.reconstruction?.id]);

  useEffect(() => {
    if (!playing || reduceMotion) return;
    const timer = window.setInterval(() => {
      setFrameIndex((index) => {
        if (index >= frames.length - 1) {
          setPlaying(false);
          return index;
        }
        return index + 1;
      });
    }, frameMs);
    return () => window.clearInterval(timer);
  }, [playing, frameMs, frames.length, reduceMotion]);

  useEffect(() => {
    if (!detailsOpen || !desk?.selected_revision_id) {
      setHistory(null);
      return;
    }
    void api<History>(`/api/v1/passages/${desk.selected_revision_id}/history`)
      .then(setHistory)
      .catch((reason: Error) => setError(reason.message));
  }, [detailsOpen, desk?.selected_revision_id, desk?.annotations]);

  async function flushDraft() {
    if (!projectRef.current) return;
    await api("/api/v1/draft", { method: "PUT", body: JSON.stringify({ text: draft }) });
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await flushDraft();
      await api("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify({ title: title.trim() || "Untitled" }),
      });
      setTitle("");
      loadedFor.current = null;
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function importProject(event: FormEvent) {
    event.preventDefault();
    if (!archive) return;
    setError("");
    try {
      const encoded = await readFile(archive);
      const imported = await api<ProjectSummary>("/api/v1/projects/import", {
        method: "POST",
        body: JSON.stringify({ content_base64: encoded }),
      });
      setArchive(null);
      loadedFor.current = null;
      await reload();
      await openProject(imported.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function openProject(projectId: string) {
    if (projectId === projectRef.current) return;
    setError("");
    try {
      await flushDraft();
      await api("/api/v1/projects/open", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      });
      loadedFor.current = null;
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  function writeEditor(text: string) {
    setDraft(text);
    if (editorRef.current) editorRef.current.value = text;
  }

  async function restore(revisionId: string) {
    setError("");
    try {
      const saved = await api<Revision>(`/api/v1/passages/${revisionId}/select`, { method: "POST" });
      writeEditor(saved.text);
      editorRef.current?.focus();
      const next = await api<Desk>("/api/v1/desk");
      setDesk(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function saveRevision() {
    setError("");
    try {
      await api<Revision>("/api/v1/passages", {
        method: "POST",
        body: JSON.stringify({ text: draft }),
      });
      setNotice("The passage is saved.");
      const next = await api<Desk>("/api/v1/desk");
      setDesk(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function reject(revisionId: string) {
    setError("");
    try {
      await api(`/api/v1/passages/${revisionId}/reject`, { method: "POST" });
      const next = await api<Desk>("/api/v1/desk");
      setDesk(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  function samplingBody(): Record<string, unknown> {
    const temperatureValue = Number(temperature);
    const topKValue = Number(topK);
    const topPValue = Number(topP);
    if (!Number.isFinite(temperatureValue) || temperatureValue < 0) {
      throw new Error("Temperature must be zero or greater.");
    }
    if (!Number.isInteger(topKValue) || topKValue < 0) {
      throw new Error("Top-k must be a whole number, zero or greater.");
    }
    if (!Number.isFinite(topPValue) || topPValue <= 0 || topPValue > 1) {
      throw new Error("Top-p must be greater than zero and at most one.");
    }
    const body: Record<string, unknown> = {
      client_request_id: crypto.randomUUID(),
      retained_level_count: retained,
      candidate_count: candidateCount,
      temperature: temperatureValue,
      top_k: topKValue,
      top_p: topPValue,
    };
    if (seedText.trim() !== "") {
      const seed = Number(seedText);
      if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) {
        throw new Error("The seed must be a whole number from 0 through 4294967295.");
      }
      body.base_seed = seed;
    }
    return body;
  }

  async function startJob(path: string, body: Record<string, unknown>) {
    setError("");
    setNotice("");
    if (tokens?.too_long || draft === "") {
      setError(draft === "" ? "Enter a nonempty passage." : `Choose a passage of at most ${tokens?.text_length ?? 128} tokens.`);
      return;
    }
    try {
      await flushDraft();
      const queued = await api<Job>(path, { method: "POST", body: JSON.stringify(body) });
      setJob(queued);
      const next = await api<Desk>("/api/v1/desk");
      setDesk(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function addAnnotation(kind: "note" | "tag", value: string) {
    if (!desk?.selected_revision_id || value.trim() === "") return;
    setError("");
    try {
      await api<Annotation>("/api/v1/annotations", {
        method: "POST",
        body: JSON.stringify({ revision_id: desk.selected_revision_id, kind, value: value.trim() }),
      });
      if (kind === "note") setNote("");
      else setTag("");
      const next = await api<Desk>("/api/v1/desk");
      setDesk(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const sourceId =
    variationJob?.result?.passage_revision_id ?? variationJob?.request.passage_revision_id ?? null;
  const reconstructionSourceId =
    desk?.reconstruction?.result?.passage_revision_id ??
    desk?.reconstruction?.request.passage_revision_id ??
    null;
  const pinned = desk?.revisions.find((item) => item.id === (pinnedId ?? sourceId)) ?? null;
  const frame = frames[Math.min(frameIndex, Math.max(frames.length - 1, 0))];
  const blocked = jobActive || Boolean(tokens?.too_long) || draft === "";

  return (
    <div className="desk">
      <header className="top">
        <p className="mark">Openwound</p>
        <nav className="places" aria-label="Workspace">
          <button type="button" aria-current={place === "desk" ? "true" : undefined} onClick={() => setPlace("desk")}>
            Desk
          </button>
          <button
            type="button"
            aria-current={place === "correspondences" ? "true" : undefined}
            onClick={() => setPlace("correspondences")}
          >
            Correspondences
          </button>
        </nav>
        <p className="worker">{workerLabel(status)}</p>
      </header>
      <div className={place === "desk" ? "columns" : "columns correspondences-columns"}>
        <aside className="rail">
          <form onSubmit={createProject}>
            <label>
              New project
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Untitled" />
            </label>
            <button type="submit">Create project</button>
          </form>
          <form onSubmit={(event) => void importProject(event)}>
            <label>
              Project archive
              <input
                type="file"
                accept=".zip,application/zip"
                onChange={(event) => setArchive(event.target.files?.[0] ?? null)}
              />
            </label>
            <button type="submit" disabled={!archive}>
              Import project
            </button>
          </form>
          <ul className="projects">
            {projects.map((project) => (
              <li key={project.id}>
                <button
                  type="button"
                  aria-current={project.id === desk?.project.id ? "true" : undefined}
                  onClick={() => void openProject(project.id)}
                >
                  {project.title}
                </button>
              </li>
            ))}
          </ul>
        </aside>
        {place === "correspondences" ? (
          <Correspondences projectId={desk?.project.id ?? null} />
        ) : (
          <>
        <main>
          {!desk && <p className="quiet">Create a project to begin a passage.</p>}
          {desk && (
            <>
              <h1>{desk.project.title}</h1>
              <div className="banner" aria-live="polite">
                {error && <p className="error">{error}</p>}
                {notice && <p>{notice}</p>}
                {job && (
                  <p>
                    <span className="state">{job.state}</span> {progressLabel(job)}
                    {jobActive && (
                      <button
                        type="button"
                        onClick={() =>
                          void api<Job>(`/api/v1/jobs/${job.id}/cancel`, { method: "POST" })
                            .then(setJob)
                            .catch((reason: Error) => setError(reason.message))
                        }
                      >
                        Cancel
                      </button>
                    )}
                  </p>
                )}
              </div>
              <label className="passage-label" htmlFor="passage">
                Passage
              </label>
              <textarea
                id="passage"
                ref={editorRef}
                key={desk.project.id}
                defaultValue={desk.draft.text}
                onChange={(event) => setDraft(event.target.value)}
                spellCheck
              />
              <p className="count">
                {tokens
                  ? `${tokens.token_count} ${tokens.token_count === 1 ? "token" : "tokens"}`
                  : "Counting tokens."}
                {tokens?.too_long ? ` The limit for a model run is ${tokens.text_length}.` : ""}
              </p>
              <div className="actions">
                <button type="button" onClick={() => void saveRevision()} disabled={draft === ""}>
                  Save revision
                </button>
                <button
                  type="button"
                  disabled={blocked}
                  onClick={() =>
                    void startJob("/api/v1/jobs/reconstruct", { client_request_id: crypto.randomUUID() })
                  }
                >
                  Reconstruct
                </button>
                <button
                  type="button"
                  disabled={blocked}
                  onClick={() => {
                    try {
                      void startJob("/api/v1/jobs/variants", samplingBody());
                    } catch (reason) {
                      setError(reason instanceof Error ? reason.message : String(reason));
                    }
                  }}
                >
                  Vary
                </button>
                <button type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen((open) => !open)}>
                  Provenance
                </button>
              </div>
              <div className="vary">
                <label>
                  Levels kept
                  <input
                    type="range"
                    min={0}
                    max={12}
                    value={retained}
                    onChange={(event) => setRetained(Number(event.target.value))}
                  />
                  <span>{retained}</span>
                </label>
                <p>
                  {varyCaption(retained)} {candidateCount} {candidateCount === 1 ? "candidate" : "candidates"}.
                </p>
                <button type="button" aria-expanded={advanced} onClick={() => setAdvanced((open) => !open)}>
                  Sampling
                </button>
                {advanced && (
                  <div className="advanced">
                    <label>
                      Temperature
                      <input value={temperature} onChange={(event) => setTemperature(event.target.value)} />
                    </label>
                    <label>
                      Top-k
                      <input value={topK} onChange={(event) => setTopK(event.target.value)} />
                    </label>
                    <label>
                      Top-p
                      <input value={topP} onChange={(event) => setTopP(event.target.value)} />
                    </label>
                    <label>
                      Seed
                      <input
                        value={seedText}
                        onChange={(event) => setSeedText(event.target.value)}
                        placeholder="Chosen when the job starts"
                      />
                    </label>
                    <label>
                      Candidates
                      <input
                        type="number"
                        min={1}
                        max={8}
                        value={candidateCount}
                        onChange={(event) => setCandidateCount(Number(event.target.value))}
                      />
                    </label>
                  </div>
                )}
              </div>
              {frames.length > 0 && frame && (
                <section className="reconstruction" aria-label="Reconstruction">
                  <h2>Reconstruction</h2>
                  <p>Level {frame.level} of {frames.length}.</p>
                  <label>
                    Level
                    <input
                      type="range"
                      min={1}
                      max={frames.length}
                      value={frame.level}
                      onChange={(event) => {
                        setPlaying(false);
                        setFrameIndex(Number(event.target.value) - 1);
                      }}
                    />
                  </label>
                  <div className="actions">
                    <button type="button" onClick={() => setFrameIndex((index) => Math.max(0, index - 1))}>
                      Previous level
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setFrameIndex((index) => Math.min(frames.length - 1, index + 1))
                      }
                    >
                      Next level
                    </button>
                    {reduceMotion ? (
                      <p>Reduced motion is on. Step through the levels.</p>
                    ) : (
                      <button type="button" onClick={() => setPlaying((value) => !value)}>
                        {playing ? "Pause" : "Play"}
                      </button>
                    )}
                    <label>
                      Frame timing
                      <select value={frameMs} onChange={(event) => setFrameMs(Number(event.target.value))}>
                        <option value={400}>Fast</option>
                        <option value={800}>Steady</option>
                        <option value={1600}>Slow</option>
                      </select>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={showOriginal}
                        onChange={(event) => setShowOriginal(event.target.checked)}
                      />
                      Show the original beside this frame
                    </label>
                  </div>
                  <div className={showOriginal ? "pair" : undefined}>
                    <article>
                      <h3>Model reconstruction</h3>
                      <p className="prose">{passageText(frame.text)}</p>
                    </article>
                    {showOriginal && (
                      <article>
                        <h3>Original</h3>
                        <p className="prose">
                          {passageText(
                            desk.revisions.find((item) => item.id === reconstructionSourceId)?.text ?? "",
                          )}
                        </p>
                      </article>
                    )}
                  </div>
                  <button type="button" onClick={() => void restore(frame.revision_id)}>
                    Adopt this frame
                  </button>
                  {frame.raw_token_ids && (
                    <details>
                      <summary>Raw token ids</summary>
                      <p className="raw">{frame.raw_token_ids.join(" ")}</p>
                    </details>
                  )}
                </section>
              )}
              {candidates.length > 0 && (
                <section aria-label="Candidates">
                  <h2>Candidates</h2>
                  <p>
                    {varyCaption(variationJob?.request.retained_level_count ?? retained)}{" "}
                    {variationJob?.request.base_seed !== undefined
                      ? `Base seed ${variationJob.request.base_seed}.`
                      : ""}
                  </p>
                  <ul className="cards">
                    {candidates.map((candidate) => (
                      <CandidateCard
                        key={candidate.revision_id}
                        candidate={candidate}
                        earlier={candidates.slice(0, candidate.index)}
                        pinned={comparingId === candidate.revision_id ? pinned : null}
                        onAdopt={() => void restore(candidate.revision_id)}
                        onEdit={() => void restore(candidate.revision_id).then(() => editorRef.current?.focus())}
                        onCompare={() =>
                          setComparingId((current) =>
                            current === candidate.revision_id ? null : candidate.revision_id,
                          )
                        }
                        onReject={() => void reject(candidate.revision_id)}
                        rejected={
                          desk.revisions.find((item) => item.id === candidate.revision_id)?.disposition ===
                          "rejected"
                        }
                      />
                    ))}
                  </ul>
                </section>
              )}
              {detailsOpen && (
                <section className="inspector" aria-label="Provenance">
                  <h2>Provenance</h2>
                  {!selected && <p>Save a passage to inspect it.</p>}
                  {selected && history && (
                    <>
                      <p>Origin: {history.revision.origin_kind}</p>
                      {history.revision.parents.length === 0 && <p>This is the first saved passage.</p>}
                      {history.revision.parents.map((parent) => (
                        <p key={`${parent.relationship}-${parent.parent_id}`}>
                          {parent.relationship.replaceAll("_", " ")} {parent.parent_id}
                        </p>
                      ))}
                      {recordedRuns(history).length > 1
                        ? recordedRuns(history).map((run) => (
                            <p key={run.id}>
                              Operation: {run.operation}
                              {run.parameters.donor
                                ? ` Donor ${run.parameters.donor.owner_kind} ${run.parameters.donor.start_byte}–${run.parameters.donor.end_byte}`
                                : ""}
                              {run.parameters.host_revision_id ? ` Host ${run.parameters.host_revision_id}` : ""}
                            </p>
                          ))
                        : history.run && (
                        <>
                          <p>Operation: {history.run.operation}</p>
                          {history.run.parameters.donor && (
                            <p>
                              Donor {history.run.parameters.donor.owner_kind} {history.run.parameters.donor.start_byte}–
                              {history.run.parameters.donor.end_byte}
                            </p>
                          )}
                          {history.run.parameters.host_revision_id && (
                            <p>Host {history.run.parameters.host_revision_id}</p>
                          )}
                          {history.run.parameters.retained_level_count !== undefined &&
                            history.run.parameters.retained_level_count !== null && (
                              <p>Levels kept: {history.run.parameters.retained_level_count}</p>
                            )}
                          {history.run.parameters.base_seed !== undefined &&
                            history.run.parameters.base_seed !== null && (
                              <p>Base seed: {history.run.parameters.base_seed}</p>
                            )}
                          {history.run.parameters.display_policy && (
                            <p>Display: {history.run.parameters.display_policy}</p>
                          )}
                        </>
                      )}
                      <p className="raw">SHA-256 {history.revision.text_sha256}</p>
                      <ul>
                        {history.annotations.map((item) => (
                          <li key={item.id}>
                            {item.kind}: {item.value}
                          </li>
                        ))}
                      </ul>
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          void addAnnotation("note", note);
                        }}
                      >
                        <label>
                          Note
                          <textarea value={note} onChange={(event) => setNote(event.target.value)} />
                        </label>
                        <button type="submit">Add note</button>
                      </form>
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          void addAnnotation("tag", tag);
                        }}
                      >
                        <label>
                          Tag
                          <input value={tag} onChange={(event) => setTag(event.target.value)} />
                        </label>
                        <button type="submit">Add tag</button>
                      </form>
                    </>
                  )}
                </section>
              )}
              <p className="exports">
                <a href="/api/v1/exports/reading.json" download>
                  Download JSON
                </a>
                <a href="/api/v1/exports/reading.txt" download>
                  Download text
                </a>
              </p>
            </>
          )}
        </main>
        <aside className="history">
          <h2>History</h2>
          <ul>
            {(desk?.revisions ?? []).slice().reverse().map((revision) => (
              <li key={revision.id}>
                <button
                  type="button"
                  aria-current={revision.id === desk?.selected_revision_id ? "true" : undefined}
                  onClick={() => void restore(revision.id)}
                >
                  <span className="origin">{revision.origin_kind}</span>
                  {revision.disposition === "rejected" && <span className="flag">Rejected</span>}
                  <span className="preview">{passageText(revision.text).slice(0, 96)}</span>
                </button>
                <button type="button" onClick={() => setPinnedId(revision.id)}>
                  Pin
                </button>
              </li>
            ))}
          </ul>
          {!desk?.revisions.length && <p className="quiet">Saved passages appear here.</p>}
        </aside>
          </>
        )}
      </div>
    </div>
  );
}

function CandidateCard({
  candidate,
  earlier,
  pinned,
  rejected,
  onAdopt,
  onEdit,
  onCompare,
  onReject,
}: {
  candidate: Candidate;
  earlier: Candidate[];
  pinned: Revision | null;
  rejected: boolean;
  onAdopt: () => void;
  onEdit: () => void;
  onCompare: () => void;
  onReject: () => void;
}) {
  const duplicate = earlier.some((item) => item.text === candidate.text);
  return (
    <li>
      <article>
        <header>
          <h3>Candidate {candidate.index + 1}</h3>
          <p>Seed {candidate.seed}</p>
          {duplicate && <p className="flag">Duplicate of an earlier candidate.</p>}
          {rejected && <p className="flag">Rejected</p>}
        </header>
        {pinned ? (
          <p className="prose diff">
            <span className="legend">Struck words were in the comparison passage. Underlined words are new.</span>
            {wordDiff(pinned.text, candidate.text).map((piece, index) =>
              piece.kind === "same" ? (
                <span key={index}>{piece.text}</span>
              ) : piece.kind === "removed" ? (
                <del key={index}>{piece.text}</del>
              ) : (
                <ins key={index}>{piece.text}</ins>
              ),
            )}
          </p>
        ) : (
          <p className="prose">{passageText(candidate.text)}</p>
        )}
        <div className="actions">
          <button type="button" onClick={onAdopt}>
            Adopt
          </button>
          <button type="button" onClick={onEdit}>
            Edit
          </button>
          <button type="button" onClick={onCompare}>
            {pinned ? "Hide comparison" : "Compare"}
          </button>
          <button type="button" onClick={onReject}>
            Reject
          </button>
        </div>
      </article>
    </li>
  );
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      const comma = value.indexOf(",");
      resolve(comma >= 0 ? value.slice(comma + 1) : value);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

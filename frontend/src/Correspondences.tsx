import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, type Job } from "./api";
import { Compare } from "./Compare";
import { Work } from "./Work";

type Anchor = {
  owner_kind: string;
  owner_id: string;
  text_sha256: string;
  start_byte: number;
  end_byte: number;
  slice_sha256: string;
};

type SourceSummary = {
  id: string;
  family_id: string;
  title: string;
  author: string | null;
  byte_length: number;
};

type Fragment = {
  id: string;
  text: string;
  start_byte: number;
  end_byte: number;
  anchor: Anchor;
  window_count: number;
};

type Context = {
  title: string;
  author: string | null;
  before: Fragment | null;
  focus: Fragment | null;
  after: Fragment | null;
};

type Span = {
  start_byte: number;
  end_byte: number;
  label: string;
  text: string;
};

type Hit = {
  title: string;
  author: string | null;
  text: string;
  reason: string;
  reasons: { view: string; reason: string }[];
  matched_spans: Span[];
  folded: boolean;
  also: { title: string }[];
  anchor: Anchor;
  source_id: string;
};

type Encounter = {
  id: string;
  hits: Hit[];
  semantic: { state: string; job_id?: string; message?: string };
};

type Correspondence = {
  id: string;
  title: string;
  disposition: string;
  members: { ordinal: number; title: string | null; text: string; anchor: Anchor }[];
  interpretations: { id: string; body: string; producer: string; created_at: string }[];
};

function keyOf(anchor: Anchor): string {
  return `${anchor.owner_id}:${anchor.start_byte}:${anchor.end_byte}`;
}

function longestPhrases(spans: Span[]): Span[] {
  const exact = spans.filter((span) => span.label === "exact");
  return exact.filter(
    (span) => !exact.some((other) => other.text.length > span.text.length && other.text.includes(span.text)),
  );
}

function producerLabel(producer: string): string {
  if (producer === "model") return "Proposed by a model";
  if (producer === "adapted") return "Adapted from a model";
  return "Written by the artist";
}

function dispositionLabel(disposition: string): string {
  if (disposition === "retained") return "Kept";
  if (disposition === "set_aside") return "Set aside";
  if (disposition === "rejected") return "Rejected";
  return "Open";
}

async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

export function Correspondences({ projectId }: { projectId: string | null }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [fragments, setFragments] = useState<Fragment[]>([]);
  const [context, setContext] = useState<Context | null>(null);
  const [phrase, setPhrase] = useState("");
  const [found, setFound] = useState<(Anchor & { preview?: string })[]>([]);
  const [hits, setHits] = useState<Hit[]>([]);
  const [encounterId, setEncounterId] = useState<string | null>(null);
  const [semantic, setSemantic] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Anchor[]>([]);
  const [title, setTitle] = useState("");
  const [interpretation, setInterpretation] = useState("");
  const [saved, setSaved] = useState<Correspondence | null>(null);
  const [savedList, setSavedList] = useState<{ id: string; title: string; disposition: string }[]>([]);
  const [importTitle, setImportTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [pasted, setPasted] = useState("");
  const [familyId, setFamilyId] = useState("");
  const [error, setError] = useState("");
  const [workEntries, setWorkEntries] = useState<{ id: string; revision_id: string; text: string; removed: boolean }[]>([]);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!projectId) {
      setSources([]);
      setSavedList([]);
      return;
    }
    let cancel = false;
    Promise.all([
      api<{ sources: SourceSummary[] }>(`/api/v1/projects/${projectId}/sources`),
      api<{ correspondences: { id: string; title: string; disposition: string }[] }>(
        `/api/v1/projects/${projectId}/correspondences`,
      ),
    ])
      .then(([sourcePage, correspondencePage]) => {
        if (cancel) return;
        setSources(sourcePage.sources);
        setSavedList(correspondencePage.correspondences);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      });
    return () => {
      cancel = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !jobId) return;
    const timer = window.setInterval(() => {
      void api<Job>(`/api/v1/jobs/${jobId}`)
        .then((job) => {
          if (job.state === "queued" || job.state === "running") return;
          setJobId(null);
          if (job.state === "succeeded") {
            const focus = context?.focus;
            if (focus) void search(["lexical", "semantic"], focus.text, focus.anchor);
            return;
          }
          setSemantic(job.error?.message || "Related meaning is not available.");
        })
        .catch((reason: Error) => setError(reason.message));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, jobId, context]);

  async function refreshLists(id: string) {
    const [sourcePage, correspondencePage] = await Promise.all([
      api<{ sources: SourceSummary[] }>(`/api/v1/projects/${id}/sources`),
      api<{ correspondences: { id: string; title: string; disposition: string }[] }>(
        `/api/v1/projects/${id}/correspondences`,
      ),
    ]);
    setSources(sourcePage.sources);
    setSavedList(correspondencePage.correspondences);
  }

  async function importPayload(payload: Record<string, string>) {
    if (!projectId) return;
    setError("");
    const imported = await api<SourceSummary>(`/api/v1/projects/${projectId}/sources`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setNotice(`Imported ${imported.title}, ${imported.byte_length} bytes.`);
    setPasted("");
    await refreshLists(projectId);
    await openSource(imported.id);
  }

  async function openSource(id: string) {
    if (!projectId) return;
    setSourceId(id);
    setContext(null);
    setHits([]);
    const page = await api<{ fragments: Fragment[] }>(
      `/api/v1/projects/${projectId}/sources/${id}/fragments`,
    );
    setFragments(page.fragments);
  }

  async function openSpan(anchor: Anchor) {
    if (!projectId) return;
    const next = await api<Context>(
      `/api/v1/projects/${projectId}/sources/${anchor.owner_id}/context?start_byte=${anchor.start_byte}&end_byte=${anchor.end_byte}`,
    );
    setContext(next);
    setSourceId(anchor.owner_id);
  }

  async function showOccurrences(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !sourceId || !phrase.trim()) return;
    setError("");
    const result = await api<{ occurrences: (Anchor & { preview?: string })[] }>(
      `/api/v1/projects/${projectId}/sources/${sourceId}/occurrences?text=${encodeURIComponent(phrase)}`,
    );
    setFound(result.occurrences);
    dialogRef.current?.showModal();
  }

  async function search(
    views: string[],
    text: string,
    anchor: { owner_id: string; start_byte: number; end_byte: number },
  ) {
    if (!projectId) return;
    setError("");
    const result = await api<Encounter>(`/api/v1/projects/${projectId}/encounters`, {
      method: "POST",
      body: JSON.stringify({
        text,
        source_id: anchor.owner_id,
        start_byte: anchor.start_byte,
        end_byte: anchor.end_byte,
        views,
      }),
    });
    setHits(result.hits);
    setEncounterId(result.id);
    setSemantic(result.semantic.message || "");
    setJobId(result.semantic.state === "queued" ? result.semantic.job_id || null : null);
    if (!result.hits.length && result.semantic.state !== "queued") {
      setNotice("No other passage matched.");
    }
  }

  function toggle(anchor: Anchor) {
    setChosen((current) => {
      const key = keyOf(anchor);
      if (current.some((item) => keyOf(item) === key)) return current.filter((item) => keyOf(item) !== key);
      return [...current, anchor];
    });
  }

  async function saveCorrespondence(event: FormEvent) {
    event.preventDefault();
    if (!projectId || chosen.length < 2) return;
    setError("");
    const created = await api<Correspondence>(`/api/v1/projects/${projectId}/correspondences`, {
      method: "POST",
      body: JSON.stringify({
        title,
        interpretation,
        producer: "artist",
        encounter_id: encounterId,
        members: chosen,
      }),
    });
    setSaved(created);
    setNotice("Correspondence saved.");
    await refreshLists(projectId);
  }

  async function reopen(id: string) {
    if (!projectId) return;
    setSaved(await api<Correspondence>(`/api/v1/projects/${projectId}/correspondences/${id}`));
  }

  async function mark(disposition: string) {
    if (!projectId || !saved) return;
    setSaved(
      await api<Correspondence>(`/api/v1/projects/${projectId}/correspondences/${saved.id}/disposition`, {
        method: "POST",
        body: JSON.stringify({ disposition }),
      }),
    );
    await refreshLists(projectId);
  }

  async function addInterpretation(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !saved || !interpretation.trim()) return;
    setSaved(
      await api<Correspondence>(`/api/v1/projects/${projectId}/correspondences/${saved.id}/interpretation`, {
        method: "POST",
        body: JSON.stringify({ body: interpretation, producer: "artist" }),
      }),
    );
    setInterpretation("");
    await refreshLists(projectId);
  }

  if (!projectId) return <main className="correspondences"><p className="quiet">Create a project to import a source.</p></main>;

  const focus = context?.focus;

  return (
    <main className="correspondences">
      <h1>Correspondences</h1>
      <div className="banner" aria-live="polite">
        {error && <p className="error">{error}</p>}
        {notice && <p>{notice}</p>}
        {semantic && <p>{semantic}</p>}
      </div>
      <div className="reading">
        <section>
          <h2>Import</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void importPayload({
                title: importTitle,
                author,
                text: pasted,
                ...(familyId ? { family_id: familyId } : {}),
              }).catch((reason: Error) => setError(reason.message));
            }}
          >
            <label>
              Title
              <input value={importTitle} onChange={(event) => setImportTitle(event.target.value)} />
            </label>
            <label>
              Author
              <input value={author} onChange={(event) => setAuthor(event.target.value)} />
            </label>
            <label>
              Same work as
              <select value={familyId} onChange={(event) => setFamilyId(event.target.value)}>
                <option value="">A new source</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.family_id}>
                    {source.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Pasted text
              <textarea value={pasted} onChange={(event) => setPasted(event.target.value)} />
            </label>
            <button type="submit" disabled={!pasted.trim()}>
              Import text
            </button>
          </form>
          <label>
            UTF-8 file
            <input
              type="file"
              accept=".txt,.md,text/plain,text/markdown"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (!file) return;
                void fileBase64(file)
                  .then((content_base64) =>
                    importPayload({
                      title: importTitle || file.name,
                      author,
                      filename: file.name,
                      content_base64,
                      ...(familyId ? { family_id: familyId } : {}),
                    }),
                  )
                  .catch((reason: Error) => setError(reason instanceof ApiError ? reason.message : reason.message));
              }}
            />
          </label>
          <h2>Sources</h2>
          <ul className="passages">
            {sources.map((source) => (
              <li key={source.id}>
                <button type="button" aria-current={source.id === sourceId ? "true" : undefined} onClick={() => void openSource(source.id).catch((reason: Error) => setError(reason.message))}>
                  {source.title}
                  {source.author ? `, ${source.author}` : ""}
                </button>
              </li>
            ))}
          </ul>
          {!sources.length && <p className="quiet">Imported sources appear here.</p>}
          <h2>Saved</h2>
          <ul className="passages">
            {savedList.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => void reopen(item.id).catch((reason: Error) => setError(reason.message))}>
                  {item.title || "Untitled correspondence"}
                  <span className="legend">{dispositionLabel(item.disposition)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section>
          {fragments.length > 0 && (
            <>
              <h2>Passages</h2>
              <ul className="passages">
                {fragments.map((fragment) => (
                  <li key={fragment.id}>
                    <button type="button" onClick={() => void openSpan(fragment.anchor).catch((reason: Error) => setError(reason.message))}>
                      {fragment.text}
                    </button>
                    {fragment.window_count > 0 && (
                      <p className="legend">{fragment.window_count} model windows recorded. The paragraph is intact.</p>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          {sourceId && (
            <form onSubmit={(event) => void showOccurrences(event).catch((reason: Error) => setError(reason.message))}>
              <label>
                Find a phrase in this source
                <input value={phrase} onChange={(event) => setPhrase(event.target.value)} />
              </label>
              <button type="submit">Show occurrences</button>
            </form>
          )}
          {context && (
            <article className="context">
              <h2>{context.title}</h2>
              {context.author && <p className="legend">{context.author}</p>}
              {context.before && <p className="prose quiet">{context.before.text}</p>}
              {focus && <p className="prose">{focus.text}</p>}
              {context.after && <p className="prose quiet">{context.after.text}</p>}
              {focus && (
                <p>
                  <button type="button" aria-pressed={chosen.some((item) => keyOf(item) === keyOf(focus.anchor))} onClick={() => toggle(focus.anchor)}>
                    {chosen.some((item) => keyOf(item) === keyOf(focus.anchor)) ? "Selected" : "Select this passage"}
                  </button>
                  <button type="button" onClick={() => void search(["lexical"], focus.text, focus.anchor).catch((reason: Error) => setError(reason.message))}>
                    Shared words
                  </button>
                  <button type="button" onClick={() => void search(["lexical", "semantic"], focus.text, focus.anchor).catch((reason: Error) => setError(reason.message))}>
                    Related meaning
                  </button>
                </p>
              )}
            </article>
          )}
          <Work
            projectId={projectId}
            donor={focus && context ? { text: focus.text, title: context.title, anchor: focus.anchor } : null}
            onEncounter={(text, anchor) => void search(["lexical", "semantic"], text, anchor).catch((reason: Error) => setError(reason.message))}
            onEntries={setWorkEntries}
          />
          <Compare
            projectId={projectId}
            passage={focus ? { id: focus.id, text: focus.text, title: context?.title || "Passage" } : null}
            entries={workEntries}
          />
          <p>
            <button
              type="button"
              onClick={() => {
                if (!projectId) return;
                void api<{ text: string; title: string; anchor: Anchor; reason: string }>(
                  `/api/v1/projects/${projectId}/encounters/browse`,
                  { method: "POST" },
                )
                  .then((passage) => {
                    setNotice(passage.reason);
                    return openSpan(passage.anchor);
                  })
                  .catch((reason: Error) => setError(reason.message));
              }}
            >
              Another passage
            </button>
          </p>
          {hits.length > 0 && (
            <section>
              <h2>Encounters</h2>
              <ul className="hits">
                {hits.map((hit) => (
                  <li key={keyOf(hit.anchor)}>
                    <article>
                      <h3>{hit.title}{hit.author ? `, ${hit.author}` : ""}</h3>
                      <p className="prose">{hit.text}</p>
                      <ul className="reasons">
                        {(hit.reasons?.length ? hit.reasons : [{ reason: hit.reason }]).map((item) => (
                          <li key={item.reason}>{item.reason}</li>
                        ))}
                      </ul>
                      <details>
                        <summary>Why this appeared</summary>
                        {longestPhrases(hit.matched_spans || []).map((span) => (
                          <p key={`${span.start_byte}-${span.end_byte}`}>Exact phrase “{span.text}”.</p>
                        ))}
                        {hit.folded && <p>These words matched after case folding. This is not an exact quotation.</p>}
                        {hit.also?.length > 0 && (
                          <p>The same passage also appears in {hit.also.map((item) => item.title).join(", ")}.</p>
                        )}
                      </details>
                      <button type="button" onClick={() => void openSpan(hit.anchor).catch((reason: Error) => setError(reason.message))}>
                        Read in context
                      </button>
                      <button type="button" aria-pressed={chosen.some((item) => keyOf(item) === keyOf(hit.anchor))} onClick={() => toggle(hit.anchor)}>
                        {chosen.some((item) => keyOf(item) === keyOf(hit.anchor)) ? "Selected" : "Select"}
                      </button>
                    </article>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <form onSubmit={(event) => void saveCorrespondence(event).catch((reason: Error) => setError(reason.message))}>
            <h2>Save a correspondence</h2>
            <p className="legend">{chosen.length} of at least 2 passages selected.</p>
            <label>
              Title
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              Interpretation
              <textarea value={interpretation} onChange={(event) => setInterpretation(event.target.value)} />
            </label>
            <button type="submit" disabled={chosen.length < 2}>
              Save correspondence
            </button>
          </form>
          {saved && (
            <article className="saved">
              <h2>{saved.title || "Untitled correspondence"}</h2>
              <p className="legend">{dispositionLabel(saved.disposition)}</p>
              {saved.members.map((member) => (
                <p className="prose" key={member.ordinal}>
                  <span className="legend">{member.title}</span>
                  {member.text}
                </p>
              ))}
              <h3>Interpretations</h3>
              <ol>
                {saved.interpretations.map((item) => (
                  <li key={item.id}>
                    <span className="legend">{producerLabel(item.producer)}</span>
                    {item.body}
                  </li>
                ))}
              </ol>
              <form onSubmit={(event) => void addInterpretation(event).catch((reason: Error) => setError(reason.message))}>
                <button type="submit" disabled={!interpretation.trim()}>
                  Add an interpretation
                </button>
              </form>
              <p>
                <button type="button" onClick={() => void mark("retained")}>Keep</button>
                <button type="button" onClick={() => void mark("set_aside")}>Set aside</button>
                <button type="button" onClick={() => void mark("rejected")}>Reject</button>
                <button type="button" onClick={() => void mark("open")}>Reopen</button>
              </p>
            </article>
          )}
        </section>
      </div>
      <dialog ref={dialogRef} aria-labelledby="occurrences-title">
        <h2 id="occurrences-title">Occurrences</h2>
        {found.length === 0 && <p>That phrase does not occur in this source.</p>}
        <ul className="passages">
          {found.map((anchor) => (
            <li key={keyOf(anchor)}>
              <button
                type="button"
                onClick={() => {
                  dialogRef.current?.close();
                  void openSpan(anchor).catch((reason: Error) => setError(reason.message));
                }}
              >
                {anchor.preview || "This occurrence"}
              </button>
            </li>
          ))}
        </ul>
        <button type="button" onClick={() => dialogRef.current?.close()}>
          Close
        </button>
      </dialog>
    </main>
  );
}
